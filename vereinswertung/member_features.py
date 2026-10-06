"""Member submissions never change ratings; directors review through the normal importer."""

import hashlib
import json
import re
import secrets
import time
from datetime import date, datetime
from zoneinfo import ZoneInfo

from flask import g, jsonify

from vereinswertung import chesscom_import, club_roster, lichess_import, storage


def request_email(db, fallback=""):
    row = db.execute(
        "SELECT value FROM settings WHERE key='request_email'"
    ).fetchone()
    return row[0] if row else fallback


def validate_submission(data, db):
    if data.get("consent") is not True:
        raise ValueError(
            "Die vor der Partie vereinbarte Zustimmung beider Spieler bestätigen"
        )
    note = data.get("note", "")
    if not isinstance(note, str) or len(note) > 1000:
        raise ValueError("Hinweis darf höchstens 1000 Zeichen haben")
    platform = data.get("platform", "lichess")
    if platform not in ("lichess", "chesscom"):
        raise ValueError("Ungültige Plattform")
    if data.get("mode") == "match":
        first_id, second_id, day = (
            data.get("first_player"),
            data.get("second_player"),
            data.get("day"),
        )
        if (
            not isinstance(first_id, int)
            or not isinstance(second_id, int)
            or first_id == second_id
        ):
            raise ValueError("Zwei verschiedene Vereinsspieler auswählen")
        names = []
        for key, pid in [("first", first_id), ("second", second_id)]:
            if not db.execute(
                "SELECT 1 FROM players WHERE id=?", (pid,)
            ).fetchone():
                raise ValueError("Vereinsspieler nicht gefunden")
            account = (
                db.execute(
                    "SELECT username FROM lichess_accounts WHERE player_id=?",
                    (pid,),
                ).fetchone()
                if platform == "lichess"
                else None
            )
            name = data.get(key) or (account[0] if account else "")
            if not isinstance(name, str) or not re.fullmatch(
                r"[A-Za-z0-9_-]{2,30}", name.strip()
            ):
                raise ValueError(
                    "Für beide Spieler einen gültigen Online-Namen eingeben"
                )
            names.append(name.strip())
        if names[0].casefold() == names[1].casefold():
            raise ValueError("Zwei verschiedene Online-Namen eingeben")
        try:
            if (
                date.fromisoformat(day)
                > datetime.now(ZoneInfo("Europe/Berlin")).date()
            ):
                raise ValueError()
        except (TypeError, ValueError):
            raise ValueError(
                "Gültigen Spieltag auswählen, nicht in der Zukunft"
            )
        payload = {
            "platform": platform,
            "mode": "match",
            "first": names[0],
            "second": names[1],
            "first_player": first_id,
            "second_player": second_id,
            "day": day,
        }
    else:
        raise ValueError("Spieltag und zwei Vereinsspieler auswählen")
    return {**payload, "consent": True}, note.strip()


def register(
    app,
    db,
    fields,
    admin,
    director,
    is_director,
    check_limit,
    credentials,
    client_address,
    hash_password,
):
    @app.post("/api/club-members")
    def add_club_members():
        admin()
        entries = fields().get("members")
        if not isinstance(entries, list) or not 1 <= len(entries) <= 500:
            raise ValueError("1 bis 500 Mitglieder angeben")
        numbers = set()
        for entry in entries:
            if (
                not isinstance(entry, dict)
                or not isinstance(entry.get("name"), str)
                or not 2 <= len(entry["name"].strip()) <= 100
                or not isinstance(entry.get("club_number"), str)
                or not re.fullmatch(r"[0-9]{4}", entry["club_number"])
                or entry["club_number"] in numbers
            ):
                raise ValueError(
                    "Pro Mitglied eine eindeutige vierstellige Nummer und einen Namen angeben"
                )
            entry["name"] = entry["name"].strip()
            numbers.add(entry["club_number"])
            old = (
                db()
                .execute(
                    "SELECT p.name FROM club_members m JOIN players p ON p.id=m.player_id WHERE m.club_number=?",
                    (entry["club_number"],),
                )
                .fetchone()
            )
            if old and storage.normalize(old["name"]) != storage.normalize(
                entry["name"]
            ):
                raise ValueError(
                    "Mitgliedsnummer gehört bereits zu einem anderen Spieler"
                )
        from app import backup_database

        backup_database(app.config["DATABASE"])
        db().execute("BEGIN IMMEDIATE")
        try:
            club_roster.provision(db(), entries)
            storage.bump(db())
            storage.audit(
                db(),
                g.user["id"],
                "club_members_add",
                str(len(entries)) + " Listeneinträge verarbeitet",
            )
            db().commit()
        except Exception:
            db().rollback()
            raise
        return jsonify(ok=True)

    @app.post("/api/invitations")
    def invitation():
        admin()
        check_limit("invitations:" + str(g.user["id"]), 20)
        pid = fields().get("player_id")
        if pid is not None:
            member = (
                db()
                .execute(
                    "SELECT claimed FROM club_members WHERE player_id=?", (pid,)
                )
                .fetchone()
            )
            if not member or member["claimed"] is not None:
                raise ValueError(
                    "Dieser Mitgliederzugang ist nicht zur Übernahme verfügbar"
                )
        code = secrets.token_urlsafe(24)
        expires = time.time() + 7 * 86400
        with db():
            if pid is not None:
                db().execute(
                    "UPDATE invitations SET expires=? WHERE player_id=? AND used_by IS NULL",
                    (time.time(), pid),
                )
            iid = (
                db()
                .execute(
                    "INSERT INTO invitations(code_hash,created_by,created,expires,player_id) VALUES(?,?,?,?,?)",
                    (
                        hashlib.sha256(code.encode()).hexdigest(),
                        g.user["id"],
                        time.time(),
                        expires,
                        pid,
                    ),
                )
                .lastrowid
            )
            storage.audit(
                db(),
                g.user["id"],
                "invite_create",
                f"Mitgliedercode {iid} erstellt",
            )
        return jsonify(code=code, expires=expires)

    @app.post("/api/register")
    def register_member():
        check_limit("register:" + client_address(), 10)
        data = fields()
        code = data.get("code")
        if not isinstance(code, str) or not 20 <= len(code.strip()) <= 100:
            raise ValueError("Gültigen Registrierungscode eingeben")
        username, password = credentials(data)
        hashed = hashlib.sha256(code.strip().encode()).hexdigest()
        if (
            not db()
            .execute(
                "SELECT 1 FROM invitations WHERE code_hash=? AND used_by IS NULL AND expires>?",
                (hashed, time.time()),
            )
            .fetchone()
        ):
            raise ValueError("Code ungültig, abgelaufen oder bereits verwendet")
        # Hash the password before taking the database write lock.
        password_hash = hash_password(password)
        db().execute("BEGIN IMMEDIATE")
        try:
            invite = (
                db()
                .execute(
                    "SELECT id,player_id FROM invitations WHERE code_hash=? AND used_by IS NULL AND expires>?",
                    (hashed, time.time()),
                )
                .fetchone()
            )
            if not invite:
                raise ValueError(
                    "Code ungültig, abgelaufen oder bereits verwendet"
                )
            if invite["player_id"] is not None:
                member = (
                    db()
                    .execute(
                        "SELECT user_id,claimed FROM club_members WHERE player_id=?",
                        (invite["player_id"],),
                    )
                    .fetchone()
                )
                if not member or member["claimed"] is not None:
                    raise ValueError(
                        "Der Mitgliederzugang wurde bereits übernommen"
                    )
                uid = member["user_id"]
                changed = db().execute(
                    "UPDATE users SET username=?,password=?,active=1 WHERE id=? AND role='member' AND active=0 AND password='!unclaimed'",
                    (username, password_hash, uid),
                )
                if not changed.rowcount:
                    raise ValueError(
                        "Dieser Zugang ist nicht zur Übernahme verfügbar"
                    )
                db().execute(
                    "UPDATE club_members SET claimed=? WHERE player_id=?",
                    (time.time(), invite["player_id"]),
                )
            else:
                uid = (
                    db()
                    .execute(
                        "INSERT INTO users(username,password,role,created) VALUES(?,?,'member',?)",
                        (username, password_hash, time.time()),
                    )
                    .lastrowid
                )
            db().execute(
                "UPDATE invitations SET used_by=?,used=? WHERE id=?",
                (uid, time.time(), invite["id"]),
            )
            storage.audit(
                db(),
                uid,
                "member_register",
                f"Mitgliedercode {invite['id']} eingelöst",
            )
            db().commit()
        except Exception:
            db().rollback()
            raise
        return jsonify(ok=True)

    @app.get("/api/club-members")
    def club_members():
        admin()
        rows = db().execute(
            "SELECT m.*,p.name,u.username,u.active FROM club_members m JOIN players p ON p.id=m.player_id JOIN users u ON u.id=m.user_id ORDER BY p.name"
        )
        return jsonify(members=[dict(r) for r in rows])

    @app.get("/api/submission-players")
    def submission_players():
        rows = db().execute(
            "SELECT p.id,p.name,a.username FROM players p LEFT JOIN lichess_accounts a ON a.player_id=p.id ORDER BY p.name"
        )
        return jsonify(
            players=[
                {
                    "id": r["id"],
                    "name": r["name"],
                    "available": bool(r["username"]),
                    **({"username": r["username"]} if is_director() else {}),
                }
                for r in rows
            ]
        )

    @app.post("/api/players/<int:pid>/lichess")
    def set_lichess(pid):
        director()
        name = fields().get("username")
        if not isinstance(name, str) or not re.fullmatch(
            r"[A-Za-z0-9_-]{2,30}", name
        ):
            raise ValueError("Gültigen Lichess-Namen eingeben")
        if (
            not db()
            .execute("SELECT id FROM players WHERE id=?", (pid,))
            .fetchone()
        ):
            raise ValueError("Spieler nicht gefunden")
        alias = (
            db()
            .execute(
                "SELECT player_id FROM aliases WHERE name_key=?",
                (storage.normalize("Lichess: " + name),),
            )
            .fetchone()
        )
        if alias and alias[0] != pid:
            raise ValueError(
                "Dieses Lichess-Konto gehört bereits zu einem anderen Vereinsspieler"
            )
        with db():
            db().execute(
                "INSERT INTO lichess_accounts VALUES(?,?) ON CONFLICT(player_id) DO UPDATE SET username=excluded.username",
                (pid, name),
            )
            storage.audit(
                db(),
                g.user["id"],
                "lichess_account",
                f"Lichess-Konto für Spieler {pid} hinterlegt",
            )
        return jsonify(ok=True)

    @app.get("/api/settings")
    def settings():
        admin()
        return jsonify(
            request_email=request_email(db(), app.config["REQUEST_EMAIL"])
        )

    @app.post("/api/settings")
    def save_settings():
        admin()
        email = fields().get("request_email", "")
        if (
            not isinstance(email, str)
            or len(email) > 254
            or (
                email
                and not re.fullmatch(
                    r"[A-Za-z0-9.!#$%&\'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
                    email,
                )
            )
        ):
            raise ValueError("Gültige E-Mail-Adresse eingeben")
        with db():
            db().execute(
                "INSERT INTO settings VALUES('request_email',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (email,),
            )
            storage.audit(
                db(),
                g.user["id"],
                "settings",
                "Adresse für Zugangsanfragen geändert",
            )
        return jsonify(ok=True)

    @app.get("/api/submissions")
    def submissions():
        rows = db().execute(
            """SELECT s.*,u.username FROM submissions s JOIN users u ON u.id=s.owner
            WHERE (? OR s.owner=?) ORDER BY CASE WHEN s.status='pending' THEN 0 ELSE 1 END,s.created DESC LIMIT 200""",
            (is_director(), g.user["id"]),
        )
        result = []
        for r in rows:
            payload = json.loads(r["payload"])
            if not is_director():
                payload = {
                    k: v
                    for k, v in payload.items()
                    if k
                    in (
                        "platform",
                        "mode",
                        "first_player",
                        "second_player",
                        "day",
                        "consent",
                    )
                }
            result.append({**dict(r), "payload": payload})
        return jsonify(submissions=result)

    @app.post("/api/submissions/inspect")
    def inspect_submission():
        check_limit("submission-load:" + str(g.user["id"]), 10)
        data = fields()
        link = data.get("link", "")
        platform = data.get("platform", "lichess")
        if platform not in ("lichess", "chesscom"):
            raise ValueError("Ungültige Plattform")
        if data.get("pgn"):
            if platform != "chesscom" or data.get("consent") is not True:
                raise ValueError("Chess.com wählen und Zustimmung bestätigen")
            items = chesscom_import.parse_pgn(data["pgn"])
            item = items[0]
            data = {
                **data,
                "mode": "match",
                "day": item["round_dates"][0],
                "first": item["parsed"]["players"][0]["name"].split(": ", 1)[1],
                "second": item["parsed"]["players"][1]["name"].split(": ", 1)[
                    1
                ],
            }
            payload, note = validate_submission(data, db())
            expected = {
                payload["first"].casefold(),
                payload["second"].casefold(),
            }
            if any(
                {
                    p["name"].split(": ", 1)[1].casefold()
                    for p in i["parsed"]["players"]
                }
                != expected
                or i["round_dates"][0] != payload["day"]
                for i in items
            ):
                raise ValueError(
                    "Eine PGN-Einreichung muss dieselben zwei Spieler und denselben Spieltag enthalten"
                )
        elif platform == "chesscom":
            payload, note = validate_submission(data, db())
            items = chesscom_import.fetch_match(
                payload["first"], payload["second"], payload["day"], link
            )
        elif link:
            if not isinstance(link, str) or len(link.split()) != 1:
                raise ValueError("Einen einzelnen Partielink eingeben")
            if data.get("consent") is not True:
                raise ValueError("Zustimmung beider Spieler bestätigen")
            items = lichess_import.fetch_games(link.strip())
            item = items[0]
            data = {
                **data,
                "mode": "match",
                "day": item["round_dates"][0],
                "first": item["parsed"]["players"][0]["name"][9:],
                "second": item["parsed"]["players"][1]["name"][9:],
            }
            payload, note = validate_submission(data, db())
        else:
            payload, note = validate_submission(data, db())
            items = lichess_import.fetch_match(
                payload["first"], payload["second"], payload["day"]
            )
        token = secrets.token_urlsafe(32)
        with db():
            db().execute("DELETE FROM previews WHERE expires<?", (time.time(),))
            db().execute("DELETE FROM previews WHERE owner=?", (g.user["id"],))
            db().execute(
                "INSERT INTO previews VALUES(?,?,?,?,?)",
                (
                    token,
                    g.user["id"],
                    storage.revision(db()),
                    json.dumps(
                        {
                            "kind": "member-match",
                            "payload": payload,
                            "note": note,
                            "items": items,
                        }
                    ),
                    time.time() + 1800,
                ),
            )
        return jsonify(
            token=token,
            games=[
                {
                    "id": item["external_id"],
                    "played": item["played"],
                    "category": item["category"],
                    "white_player": payload["first_player"]
                    if storage.normalize(item["parsed"]["players"][0]["name"])
                    == storage.normalize(
                        (
                            "Chess.com: "
                            if platform == "chesscom"
                            else "Lichess: "
                        )
                        + payload["first"]
                    )
                    else payload["second_player"],
                    "score": item["parsed"]["games"][0]["score"],
                }
                for item in items
            ],
        )

    @app.post("/api/submissions")
    def submit():
        check_limit("submission:" + str(g.user["id"]), 10)
        data = fields()
        row = (
            db()
            .execute(
                "SELECT payload FROM previews WHERE token=? AND owner=? AND expires>?",
                (data.get("token"), g.user["id"], time.time()),
            )
            .fetchone()
        )
        if not row:
            raise ValueError(
                "Bitte zuerst Partien laden; die Auswahl ist abgelaufen"
            )
        loaded = json.loads(row["payload"])
        if loaded.get("kind") != "member-match":
            raise ValueError("Ungültige Partieauswahl")
        selected = data.get("selected")
        available = {item["external_id"]: item for item in loaded["items"]}
        if (
            not isinstance(selected, list)
            or not selected
            or any(
                not isinstance(gid, str) or gid not in available
                for gid in selected
            )
            or len(set(selected)) != len(selected)
        ):
            raise ValueError("Mindestens eine der geladenen Partien auswählen")
        if data.get("consent") is not True:
            raise ValueError("Zustimmung beider Spieler bestätigen")
        payload = {
            **loaded["payload"],
            "selected": sorted(selected),
            "items": [available[gid] for gid in sorted(selected)],
        }
        note = loaded["note"]
        encoded = json.dumps(payload, sort_keys=True)
        with db():
            if (
                db()
                .execute(
                    "SELECT 1 FROM submissions WHERE owner=? AND status='pending' AND payload=?",
                    (g.user["id"], encoded),
                )
                .fetchone()
            ):
                raise ValueError("Diese Einreichung wartet bereits auf Prüfung")
            sid = (
                db()
                .execute(
                    "INSERT INTO submissions(owner,created,payload,note) VALUES(?,?,?,?)",
                    (g.user["id"], time.time(), encoded, note),
                )
                .lastrowid
            )
            storage.audit(
                db(),
                g.user["id"],
                "submit",
                f"Partien zur Prüfung eingereicht: {sid}",
            )
        return jsonify(ok=True, id=sid)

    @app.post("/api/submissions/<int:sid>/reject")
    def reject(sid):
        director()
        reason = fields().get("reason", "")
        if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 1000:
            raise ValueError("Bitte eine kurze Begründung eingeben")
        with db():
            changed = db().execute(
                "UPDATE submissions SET status='rejected',reviewer=?,reviewed=?,response=? WHERE id=? AND status='pending'",
                (g.user["id"], time.time(), reason.strip(), sid),
            )
            if not changed.rowcount:
                raise ValueError("Einreichung ist nicht mehr offen")
            storage.audit(
                db(),
                g.user["id"],
                "reject_submission",
                f"Einreichung {sid} abgelehnt",
            )
        return jsonify(ok=True)
