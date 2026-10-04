"""Vereinswertung: public rankings, authenticated TRF import, NAS deployment."""
import base64
import csv
import hashlib
import io
import ipaddress
import json
import logging
import os
from pathlib import Path
import secrets
import sqlite3
import threading
import time
import zipfile
from contextlib import closing
from functools import lru_cache
from urllib.parse import urlparse

from flask import Flask, g, jsonify, request, send_file, send_from_directory, redirect
from werkzeug.exceptions import HTTPException
from werkzeug.security import check_password_hash, generate_password_hash

import storage
from rating import ENGINE_VERSION
import trf

ROOT = Path(__file__).resolve().parent


def load_env():
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())


def create_app(config=None):
    load_env()
    app = Flask(__name__, static_folder="static", static_url_path="/static")
    app.config.update(DATABASE=os.environ.get("DATABASE", str(ROOT / "data" / "club.sqlite")),
                      BOOTSTRAP_TOKEN=os.environ.get("BOOTSTRAP_TOKEN", ""),
                      SECURE_COOKIE=os.environ.get("SECURE_COOKIE", "true").lower() == "true",
                      PUBLIC_ORIGIN=os.environ.get("PUBLIC_ORIGIN", "").rstrip("/"),
                      TRUSTED_PROXY_IPS=os.environ.get("TRUSTED_PROXY_IPS", ""),
                      MAX_CONTENT_LENGTH=3 * 1024 * 1024)
    if config:
        app.config.update(config)
    if len(app.config["BOOTSTRAP_TOKEN"]) < 24:
        raise RuntimeError("BOOTSTRAP_TOKEN mit mindestens 24 Zeichen setzen (siehe README)")
    storage.initialize(app.config["DATABASE"])
    password_slots = threading.BoundedSemaphore(2)

    def client_address():
        peer = request.remote_addr or "unknown"
        trusted = {p.strip() for p in app.config["TRUSTED_PROXY_IPS"].split(",") if p.strip()}
        if peer in trusted:
            try:
                return str(ipaddress.ip_address(request.headers.get("CF-Connecting-IP", "")))
            except ValueError:
                pass
        return peer

    def verify_password(candidate, password):
        if not password_slots.acquire(blocking=False):
            from werkzeug.exceptions import TooManyRequests
            raise TooManyRequests("Anmeldung ausgelastet. Bitte kurz warten und erneut versuchen.")
        try:
            return check_password_hash(candidate, password)
        finally:
            password_slots.release()

    def db():
        if "db" not in g:
            g.db = storage.connect(app.config["DATABASE"])
        return g.db

    @app.teardown_appcontext
    def close_db(_error):
        if "db" in g:
            g.db.close()

    @app.before_request
    def security():
        g.user, g.session = None, None
        token = request.cookies.get("club_session", "")
        if token:
            hashed = hashlib.sha256(token.encode()).hexdigest()
            row = db().execute("""SELECT s.*,u.username,u.role,u.active FROM sessions s
                                  JOIN users u ON u.id=s.user_id WHERE s.token=? AND s.expires>? AND u.active=1""",
                               (hashed, time.time())).fetchone()
            if row:
                g.session = row
                g.user = {"id": row["user_id"], "username": row["username"], "role": row["role"]}
        if not g.user and request.method in ("GET", "HEAD"):
            if request.path == "/static/index.html":
                return redirect("/")
            if (request.path.startswith("/api/") and request.path not in ("/api/me", "/api/health")) or request.path == "/source.zip":
                return jsonify(error="Bitte anmelden"), 401
        if request.method in ("POST", "PUT", "DELETE", "PATCH"):
            origin = request.headers.get("Origin", "")
            expected = app.config["PUBLIC_ORIGIN"]
            if expected:
                valid = origin == expected
            else:
                parsed = urlparse(origin)
                valid = parsed.scheme in ("http", "https") and parsed.netloc == request.host
            if not valid:
                return jsonify(error="Anfrage stammt nicht von der App-Adresse"), 403
            public = request.path in ("/api/login", "/api/setup")
            if not public:
                if not g.user:
                    return jsonify(error="Bitte anmelden"), 401
                if not secrets.compare_digest(request.headers.get("X-CSRF-Token", ""), g.session["csrf"]):
                    return jsonify(error="Sitzung abgelaufen. Bitte Seite neu laden."), 403

    @app.after_request
    def headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if request.path.startswith("/api/") or request.path in ("/", "/static/index.html", "/source.zip"):
            response.headers["Cache-Control"] = "no-store"
        if app.config["SECURE_COOKIE"]:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    @app.errorhandler(Exception)
    def errors(error):
        if isinstance(error, HTTPException):
            return jsonify(error="Datei zu groß" if error.code == 413 else error.description), error.code
        if isinstance(error, (ValueError, ArithmeticError)):
            return jsonify(error=str(error)), 400
        if isinstance(error, sqlite3.IntegrityError):
            return jsonify(error="Datenkonflikt. Bitte Angaben prüfen und erneut versuchen."), 409
        logging.exception("Request failed")
        return jsonify(error="Die Anfrage konnte nicht gespeichert werden. Bitte erneut versuchen."), 500

    def admin():
        if not g.user or g.user["role"] != "admin":
            from werkzeug.exceptions import Forbidden
            raise Forbidden("Nur für Administratoren")

    def fields():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise ValueError("Ungültige Anfrage")
        return data

    def credentials(data):
        username, password = data.get("username"), data.get("password")
        if not isinstance(username, str) or not 3 <= len(username.strip()) <= 50 or any(ord(c) < 32 for c in username):
            raise ValueError("Benutzername: 3 bis 50 Zeichen")
        if not isinstance(password, str) or not 12 <= len(password) <= 200:
            raise ValueError("Passwort: mindestens 12 und höchstens 200 Zeichen")
        return username.strip(), password

    def check_limit(key, maximum=10):
        with db():
            db().execute("DELETE FROM attempts WHERE expires<?", (time.time(),))
            row = db().execute("SELECT count FROM attempts WHERE key=?", (key,)).fetchone()
            if row and row[0] >= maximum:
                from werkzeug.exceptions import TooManyRequests
                raise TooManyRequests("Zu viele Versuche. Bitte in 15 Minuten erneut versuchen.")
            db().execute("""INSERT INTO attempts(key,count,expires) VALUES(?,1,?)
                            ON CONFLICT(key) DO UPDATE SET count=count+1""", (key, time.time() + 900))

    @app.get("/")
    def index():
        return send_from_directory(ROOT / "static", "index.html" if g.user else "login.html")

    @app.get("/print")
    def print_rankings():
        if not g.user:
            return redirect("/")
        response = send_from_directory(ROOT / "static", "print.html")
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/health")
    def health():
        db().execute("SELECT 1").fetchone()
        return jsonify(status="ok", engine=ENGINE_VERSION)

    @app.get("/api/me")
    def me():
        return jsonify(user=g.user, csrf=g.session["csrf"] if g.session else None,
                       needs_setup=not bool(db().execute("SELECT 1 FROM users LIMIT 1").fetchone()))

    @app.post("/api/setup")
    def setup():
        data = fields()
        if db().execute("SELECT 1 FROM users LIMIT 1").fetchone():
            raise ValueError("Die App ist bereits eingerichtet")
        if not isinstance(data.get("token"), str) or not secrets.compare_digest(data["token"], app.config["BOOTSTRAP_TOKEN"]):
            check_limit("setup:" + client_address(), 10)
            return jsonify(error="Einrichtungsschlüssel ungültig"), 403
        username, password = credentials(data)
        hashed = generate_password_hash(password)
        db().execute("BEGIN IMMEDIATE")
        try:
            if db().execute("SELECT 1 FROM users LIMIT 1").fetchone():
                raise ValueError("Die App ist bereits eingerichtet")
            uid = db().execute("INSERT INTO users(username,password,role,created) VALUES(?,?,'admin',?)",
                               (username, hashed, time.time())).lastrowid
            storage.audit(db(), uid, "setup", "Administrator angelegt")
            db().commit()
        except Exception:
            db().rollback()
            raise
        return jsonify(ok=True)

    @app.post("/api/login")
    def login():
        data = fields()
        username, password = data.get("username", ""), data.get("password", "")
        if not isinstance(username, str) or not isinstance(password, str) or len(username) > 50 or len(password) > 200:
            raise ValueError("Ungültige Zugangsdaten")
        key = "login:" + hashlib.sha256((client_address() + ":" + username.casefold().strip()).encode()).hexdigest()
        user = db().execute("SELECT * FROM users WHERE username=? AND active=1", (username.strip(),)).fetchone()
        # Same scrypt cost for unknown accounts, without revealing account existence.
        candidate = user["password"] if user else app.config["DUMMY_PASSWORD"]
        # Failed attempts must never lock out a holder of valid credentials.
        if not verify_password(candidate, password) or not user:
            check_limit(key)
            return jsonify(error="Benutzername oder Passwort falsch"), 401
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with db():
            db().execute("DELETE FROM sessions WHERE expires<?", (time.time(),))
            db().execute("DELETE FROM attempts WHERE key=?", (key,))
            db().execute("INSERT INTO sessions VALUES(?,?,?,?)",
                         (hashlib.sha256(token.encode()).hexdigest(), user["id"], csrf, time.time() + 43200))
            storage.audit(db(), user["id"], "login", "Anmeldung")
        response = jsonify(user={"id": user["id"], "username": user["username"], "role": user["role"]}, csrf=csrf)
        response.set_cookie("club_session", token, httponly=True, secure=app.config["SECURE_COOKIE"],
                            samesite="Strict", max_age=43200, path="/")
        return response

    app.config["DUMMY_PASSWORD"] = generate_password_hash(secrets.token_urlsafe(24))

    @app.post("/api/logout")
    def logout():
        with db():
            db().execute("DELETE FROM sessions WHERE token=?", (g.session["token"],))
        response = jsonify(ok=True)
        response.delete_cookie("club_session", path="/")
        return response

    @app.post("/api/password")
    def password():
        data = fields()
        user = db().execute("SELECT * FROM users WHERE id=?", (g.user["id"],)).fetchone()
        check_limit("password:" + str(g.user["id"]))
        old = data.get("old_password", "")
        if not isinstance(old, str) or len(old) > 200 or not check_password_hash(user["password"], old):
            raise ValueError("Bisheriges Passwort falsch")
        _, new = credentials({"username": user["username"], "password": data.get("password")})
        with db():
            db().execute("UPDATE users SET password=? WHERE id=?", (generate_password_hash(new), user["id"]))
            db().execute("DELETE FROM sessions WHERE user_id=? AND token<>?", (user["id"], g.session["token"]))
            storage.audit(db(), user["id"], "password", "Passwort geändert")
        return jsonify(ok=True)

    @app.get("/api/rankings")
    def rankings():
        cat = request.args.get("category", "blitz")
        if cat not in ("blitz", "rapid"):
            raise ValueError("Ungültige Kategorie")
        rows = storage.ranking(db(), cat)
        return jsonify(players=rows, revision=storage.revision(db()), engine=ENGINE_VERSION)

    @app.get("/api/export.csv")
    def export_csv():
        cat = request.args.get("category", "blitz")
        if cat not in ("blitz", "rapid"):
            raise ValueError("Ungültige Kategorie")
        stream = io.StringIO()
        writer = csv.writer(stream, delimiter=";")
        writer.writerow(["Name", "Wertung", "RD", "Volatilität", "Partien", "Vorläufig"])
        for p in storage.ranking(db(), cat):
            name = p["name"]
            if name.lstrip().startswith(("=", "+", "-", "@")) or name.startswith(("\t", "\r")):
                name = "'" + name
            writer.writerow([name, p["display"], round(p["rd"], 2), p["volatility"], p["games"], "Ja" if p["provisional"] else "Nein"])
        return send_file(io.BytesIO(("\ufeff" + stream.getvalue()).encode()), mimetype="text/csv", as_attachment=True, download_name=f"vereinswertung-{cat}.csv")

    @app.get("/api/players/<int:pid>")
    def player(pid):
        p = db().execute("SELECT id,name FROM players WHERE id=?", (pid,)).fetchone()
        if not p:
            raise ValueError("Spieler nicht gefunden")
        ratings = {cat: next((r for r in storage.ranking(db(), cat) if r["id"] == pid), None) for cat in ("blitz", "rapid")}
        history = []
        for h in db().execute("""SELECT h.before,h.after,g.round,g.score,g.white,g.played,
            t.id tournament_id,t.name,t.category,t.date,o.name opponent
            FROM history h JOIN games g ON g.id=h.game_id JOIN tournaments t ON t.id=g.tournament_id
            JOIN players o ON o.id=CASE WHEN g.white=h.player_id THEN g.black ELSE g.white END
            WHERE h.player_id=? ORDER BY t.date DESC,t.sequence DESC,t.id DESC,g.round DESC,g.id DESC""", (pid,)):
            entry = dict(h)
            before, after = json.loads(h["before"]), json.loads(h["after"])
            entry.update(before=int(before["rating"]), after=int(after["rating"]),
                         diff=int(after["rating"]) - int(before["rating"]),
                         result=h["score"] if h["white"] == pid else 1 - h["score"],
                         color="Weiß" if h["white"] == pid else "Schwarz")
            history.append(entry)
        return jsonify(player=dict(p), ratings=ratings, history=history)

    @app.get("/api/tournaments")
    def tournaments():
        rows = db().execute("""SELECT t.id,t.name,t.category,t.date,t.end_date,t.active,t.owner,
            (SELECT COUNT(*) FROM games WHERE tournament_id=t.id) games,
            (SELECT MAX(round) FROM games WHERE tournament_id=t.id) rounds
            FROM tournaments t WHERE t.hidden=0 ORDER BY date DESC,sequence DESC,id DESC""")
        return jsonify(tournaments=[dict(r) for r in rows if r["active"] or (g.user and (g.user["role"] == "admin" or r["owner"] == g.user["id"]))])

    @app.get("/api/tournaments/<int:tid>")
    def tournament(tid):
        detail = storage.tournament_detail(db(), tid)
        if not detail["active"] and (not g.user or (g.user["role"] != "admin" and detail["owner"] != g.user["id"])):
            from werkzeug.exceptions import Forbidden
            raise Forbidden()
        if not g.user:
            detail.pop("director", None)
        return jsonify(detail)

    def upload(data):
        content = data.get("content", "")
        if not isinstance(content, str):
            raise ValueError("Datei fehlt")
        try:
            raw = base64.b64decode(content, validate=True)
        except ValueError:
            raise ValueError("Datei ungültig")
        if not raw or len(raw) > 1024 * 1024:
            raise ValueError("TRF-Datei muss zwischen 1 Byte und 1 MB groß sein")
        text = trf.decode(raw)
        return text, trf.parse(text)

    @app.post("/api/import/inspect")
    def inspect():
        text, parsed = upload(fields())
        return jsonify(parsed=parsed, assignments=storage.suggestions(db(), parsed),
                       players=[dict(r) for r in db().execute("SELECT id,name FROM players ORDER BY name")])

    @app.post("/api/import/preview")
    def preview():
        check_limit("preview:" + str(g.user["id"]), 60)
        data = fields()
        text, parsed = upload(data)
        filename = data.get("filename", "Turnier.trf")
        if not isinstance(filename, str) or len(filename) > 200:
            raise ValueError("Dateiname ungültig")
        payload = {"text": text, "parsed": parsed, "filename": Path(filename).name,
                   "name": data.get("name"), "category": data.get("category"),
                   "round_dates": data.get("round_dates"), "mapping": data.get("mapping", {})}
        storage.validate_payload(payload)
        db().execute("BEGIN IMMEDIATE")
        try:
            rev = storage.revision(db())
            # Entire simulated write/replay is rolled back. A preview changes no ratings.
            db().execute("SAVEPOINT simulation")
            before = {(r["id"], cat): r for cat in ("blitz", "rapid") for r in storage.ranking(db(), cat)}
            tid = storage.import_tournament(db(), payload, g.user["id"])
            detail = storage.tournament_detail(db(), tid)
            affected = []
            for cat in ("blitz", "rapid"):
                for row in storage.ranking(db(), cat):
                    prev = before.get((row["id"], cat))
                    if prev and (abs(prev["rating"] - row["rating"]) > 0.000001 or prev["games"] != row["games"]):
                        affected.append({"name": row["name"], "category": cat, "before": prev["display"], "after": row["display"]})
            db().execute("ROLLBACK TO simulation")
            db().execute("RELEASE simulation")
            token = secrets.token_urlsafe(32)
            db().execute("DELETE FROM previews WHERE expires<?", (time.time(),))
            db().execute("""DELETE FROM previews WHERE owner=? AND token NOT IN
                (SELECT token FROM previews WHERE owner=? ORDER BY expires DESC LIMIT 4)""",
                (g.user["id"], g.user["id"]))
            db().execute("INSERT INTO previews VALUES(?,?,?,?,?)", (token, g.user["id"], rev, json.dumps(payload), time.time() + 1800))
            db().commit()
        except Exception:
            db().rollback()
            raise
        return jsonify(token=token, tournament=detail, affected=affected)

    @app.post("/api/import/commit")
    def commit():
        token = fields().get("token")
        if not isinstance(token, str):
            raise ValueError("Importvorschau fehlt")
        db().execute("BEGIN IMMEDIATE")
        try:
            row = db().execute("SELECT * FROM previews WHERE token=? AND owner=? AND expires>?", (token, g.user["id"], time.time())).fetchone()
            if not row:
                raise ValueError("Vorschau abgelaufen oder bereits gespeichert. Bitte neu erstellen.")
            if row["revision"] != storage.revision(db()):
                raise ValueError("Inzwischen wurden Daten geändert. Bitte die Vorschau erneut berechnen.")
            tid = storage.import_tournament(db(), json.loads(row["payload"]), g.user["id"])
            db().execute("DELETE FROM previews WHERE token=?", (token,))
            storage.bump(db())
            storage.audit(db(), g.user["id"], "import", f"Turnier {tid} importiert")
            db().commit()
        except Exception:
            db().rollback()
            raise
        return jsonify(ok=True, tournament_id=tid)

    @app.post("/api/tournaments/<int:tid>/undo")
    def undo(tid):
        db().execute("BEGIN IMMEDIATE")
        try:
            row = db().execute("SELECT * FROM tournaments WHERE id=? AND active=1", (tid,)).fetchone()
            if not row:
                raise ValueError("Aktives Turnier nicht gefunden")
            if row["owner"] != g.user["id"] and g.user["role"] != "admin":
                from werkzeug.exceptions import Forbidden
                raise Forbidden("Nur eigene Importe dürfen zurückgenommen werden")
            if fields().get("confirm") != row["name"]:
                raise ValueError("Bitte den Turniernamen zur Bestätigung eingeben")
            db().execute("UPDATE tournaments SET active=0 WHERE id=?", (tid,))
            storage.rebuild(db())
            storage.bump(db())
            storage.audit(db(), g.user["id"], "undo", f"Turnier {tid} zurückgenommen; Folgewertungen neu berechnet")
            db().commit()
        except Exception:
            db().rollback()
            raise
        return jsonify(ok=True)

    @app.post("/api/tournaments/<int:tid>/hide")
    def hide_tournament(tid):
        admin()
        with db():
            row = db().execute("SELECT active FROM tournaments WHERE id=?", (tid,)).fetchone()
            if not row:
                raise ValueError("Turnier nicht gefunden")
            if row["active"]:
                raise ValueError("Nur zurückgenommene Turniere können ausgeblendet werden")
            db().execute("UPDATE tournaments SET hidden=1 WHERE id=?", (tid,))
            storage.audit(db(), g.user["id"], "hide_tournament", f"Turnier {tid} aus Übersicht ausgeblendet")
        return jsonify(ok=True)

    @app.get("/api/users")
    def users():
        admin()
        return jsonify(users=[dict(r) for r in db().execute("SELECT id,username,role,active FROM users ORDER BY username")])

    @app.post("/api/users")
    def add_user():
        admin()
        data = fields()
        username, password = credentials(data)
        role = data.get("role", "director")
        if role not in ("admin", "director"):
            raise ValueError("Ungültige Rolle")
        with db():
            uid = db().execute("INSERT INTO users(username,password,role,created) VALUES(?,?,?,?)",
                               (username, generate_password_hash(password), role, time.time())).lastrowid
            storage.audit(db(), g.user["id"], "user_create", f"Zugang {uid} angelegt")
        return jsonify(ok=True)

    @app.post("/api/users/<int:uid>")
    def update_user(uid):
        admin()
        data = fields()
        db().execute("BEGIN IMMEDIATE")
        try:
            user = db().execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
            if not user:
                raise ValueError("Zugang nicht gefunden")
            if "active" in data:
                if not isinstance(data["active"], bool):
                    raise ValueError("Ungültiger Kontostatus")
                if uid == g.user["id"] and not data["active"]:
                    raise ValueError("Der eigene Zugang kann nicht gesperrt werden")
                if user["role"] == "admin" and not data["active"] and db().execute("SELECT COUNT(*) FROM users WHERE role='admin' AND active=1").fetchone()[0] <= 1:
                    raise ValueError("Mindestens ein Administrator muss aktiv bleiben")
                db().execute("UPDATE users SET active=? WHERE id=?", (int(data["active"]), uid))
            if "password" in data:
                _, pw = credentials({"username": user["username"], "password": data["password"]})
                db().execute("UPDATE users SET password=? WHERE id=?", (generate_password_hash(pw), uid))
            db().execute("DELETE FROM sessions WHERE user_id=?", (uid,))
            storage.audit(db(), g.user["id"], "user_update", f"Zugang {uid} geändert")
            db().commit()
        except Exception:
            db().rollback()
            raise
        return jsonify(ok=True)

    @app.get("/api/audit")
    def audit_log():
        admin()
        return jsonify(events=[dict(r) for r in db().execute("""SELECT a.*,u.username FROM audit a
                   LEFT JOIN users u ON u.id=a.user_id ORDER BY a.id DESC LIMIT 200""")])

    @app.get("/api/backup")
    def backup_download():
        admin()
        path = backup_database(app.config["DATABASE"])
        return send_file(path, as_attachment=True, download_name=path.name)

    @app.get("/source.zip")
    def source():
        return send_file(io.BytesIO(source_archive()), mimetype="application/zip", as_attachment=True, download_name="vereinswertung-quellcode.zip")

    @lru_cache(maxsize=1)
    def source_archive():
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as z:
            for path in public_source_files():
                z.write(path, path.relative_to(ROOT))
        return output.getvalue()

    return app


SOURCE_FILES = ["app.py", "storage.py", "rating.py", "trf.py", "manage.py", "requirements.txt", "Dockerfile",
                "compose.yaml", "compose.tunnel.yaml", ".env.example", "README.md", "NOTICE.md", "LICENSE", ".dockerignore", "package.py", ".gitignore"]


def public_source_files():
    """Publish only known source paths, never arbitrary files added to folders."""
    names = SOURCE_FILES + ["docs/BERECHNUNG.md", "static/app.js", "static/index.html",
        "static/style.css", "static/icon.svg", "static/manifest.webmanifest", "static/login.html", "static/login.js",
        "static/print.html", "static/print.css", "static/print.js",
        "tests/test_app.py", "tests/test_rating.py", "tests/browser_fixture.py",
        "reference/versions.json", "reference/lila/LICENSE", "reference/scalachess/LICENSE"]
    names += [str(p.relative_to(ROOT)) for p in (ROOT / "reference").rglob("*.scala")]
    return [ROOT / name for name in names if (ROOT / name).is_file() and not (ROOT / name).is_symlink()]


def backup_database(database):
    folder = Path(database).resolve().parent / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    name = "club-" + time.strftime("%Y%m%d-%H%M%S", time.gmtime()) + "-" + secrets.token_hex(3) + ".sqlite"
    path = folder / name
    with storage.open_db(database) as src, closing(sqlite3.connect(path)) as dst:
        src.backup(dst)
    return path


def backup_loop(database):
    while True:
        try:
            folder = Path(database).resolve().parent / "backups"
            day = time.strftime("%Y%m%d", time.gmtime())
            if not folder.exists() or not list(folder.glob(f"club-{day}-*.sqlite")):
                backup_database(database)
            if folder.exists():
                files = sorted(folder.glob("club-*.sqlite"), key=lambda p: p.stat().st_mtime, reverse=True)
                for old in files[30:]:
                    old.unlink()
        except Exception:
            logging.exception("Automatic backup failed")
        time.sleep(3600)


if __name__ == "__main__":
    from waitress import serve
    app = create_app()
    threading.Thread(target=backup_loop, args=(app.config["DATABASE"],), daemon=True).start()
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8080"))
    print(f"Vereinswertung läuft auf http://{host}:{port}", flush=True)
    serve(app, host=host, port=port, threads=4, clear_untrusted_proxy_headers=True)
