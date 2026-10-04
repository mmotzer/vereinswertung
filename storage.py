"""SQLite is the single source of truth; imports and replay are atomic."""
import difflib
import hashlib
import json
import sqlite3
import time
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path

from rating import Rating, ENGINE_VERSION, game, live
from trf import normalize

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value INTEGER NOT NULL);
INSERT OR IGNORE INTO meta VALUES('revision', 0);
CREATE TABLE IF NOT EXISTS users(
 id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE COLLATE NOCASE,
 password TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin','director')),
 active INTEGER NOT NULL DEFAULT 1, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS sessions(
 token TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
 csrf TEXT NOT NULL, expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS attempts(key TEXT PRIMARY KEY, count INTEGER NOT NULL, expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS players(id INTEGER PRIMARY KEY, name TEXT NOT NULL, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS aliases(name_key TEXT PRIMARY KEY, name TEXT NOT NULL,
 player_id INTEGER NOT NULL REFERENCES players(id));
CREATE TABLE IF NOT EXISTS tournaments(
 id INTEGER PRIMARY KEY, name TEXT NOT NULL, category TEXT NOT NULL,
 date TEXT NOT NULL, end_date TEXT NOT NULL, imported REAL NOT NULL,
 owner INTEGER NOT NULL REFERENCES users(id), active INTEGER NOT NULL DEFAULT 1,
 filename TEXT NOT NULL, original TEXT NOT NULL, raw_hash TEXT NOT NULL,
 fingerprint TEXT NOT NULL, engine TEXT NOT NULL, round_dates TEXT NOT NULL,
 skipped TEXT NOT NULL, sequence INTEGER);
CREATE UNIQUE INDEX IF NOT EXISTS unique_tournament ON tournaments(fingerprint) WHERE active=1;
CREATE UNIQUE INDEX IF NOT EXISTS unique_file ON tournaments(raw_hash, category) WHERE active=1;
CREATE TABLE IF NOT EXISTS games(
 id INTEGER PRIMARY KEY, tournament_id INTEGER NOT NULL REFERENCES tournaments(id),
 round INTEGER NOT NULL, white INTEGER NOT NULL REFERENCES players(id),
 black INTEGER NOT NULL REFERENCES players(id), score REAL NOT NULL,
 played REAL NOT NULL, UNIQUE(tournament_id,round,white), UNIQUE(tournament_id,round,black));
CREATE TABLE IF NOT EXISTS ratings(
 player_id INTEGER NOT NULL REFERENCES players(id), category TEXT NOT NULL,
 rating REAL NOT NULL, rd REAL NOT NULL, volatility REAL NOT NULL,
 games INTEGER NOT NULL, latest REAL, PRIMARY KEY(player_id,category));
CREATE TABLE IF NOT EXISTS history(
 game_id INTEGER NOT NULL REFERENCES games(id), player_id INTEGER NOT NULL REFERENCES players(id),
 before TEXT NOT NULL, after TEXT NOT NULL, PRIMARY KEY(game_id,player_id));
CREATE TABLE IF NOT EXISTS previews(
 token TEXT PRIMARY KEY, owner INTEGER NOT NULL REFERENCES users(id),
 revision INTEGER NOT NULL, payload TEXT NOT NULL, expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS audit(
 id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id),
 action TEXT NOT NULL, detail TEXT NOT NULL, created REAL NOT NULL);
CREATE INDEX IF NOT EXISTS history_player ON history(player_id,game_id);
CREATE INDEX IF NOT EXISTS games_tournament ON games(tournament_id,round,id);
"""


def connect(path):
    db = sqlite3.connect(path, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=30000")
    return db


def initialize(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open_db(path) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript(SCHEMA)
        if 'sequence' not in {r[1] for r in db.execute('PRAGMA table_info(tournaments)')}:
            db.execute('ALTER TABLE tournaments ADD COLUMN sequence INTEGER')
        if 'hidden' not in {r[1] for r in db.execute('PRAGMA table_info(tournaments)')}:
            db.execute('ALTER TABLE tournaments ADD COLUMN hidden INTEGER NOT NULL DEFAULT 0')
        db.execute('UPDATE tournaments SET sequence=id WHERE sequence IS NULL')


@contextmanager
def open_db(path):
    db = connect(path)
    try:
        with db:
            yield db
    finally:
        db.close()


def audit(db, user, action, detail):
    db.execute("INSERT INTO audit(user_id,action,detail,created) VALUES(?,?,?,?)",
               (user, action, detail, time.time()))


def revision(db):
    return db.execute("SELECT value FROM meta WHERE key='revision'").fetchone()[0]


def bump(db):
    db.execute("UPDATE meta SET value=value+1 WHERE key='revision'")


def suggestions(db, parsed):
    existing = {r["name_key"]: dict(r) for r in db.execute(
        "SELECT a.name_key,a.player_id,p.name FROM aliases a JOIN players p ON p.id=a.player_id")}
    result = []
    for p in parsed["players"]:
        key = normalize(p["name"])
        exact = existing.get(key)
        matches = difflib.get_close_matches(key, existing, n=3, cutoff=0.65) if not exact else []
        result.append({"number": p["number"], "name": p["name"],
                       "player_id": exact["player_id"] if exact else None,
                       "matched_name": exact["name"] if exact else None,
                       "suggestions": list({existing[k]["player_id"]: existing[k] for k in matches}.values())})
    return result


def timestamp(day):
    # TRF has no finish times. All rounds on a date share a deterministic noon UTC.
    return datetime.fromisoformat(day).replace(hour=12, tzinfo=timezone.utc).timestamp()


def validate_payload(payload):
    if payload.get("category") not in ("blitz", "rapid"):
        raise ValueError("Bitte Blitz oder Schnellschach auswählen")
    if not isinstance(payload.get("name"), str) or not 1 <= len(payload["name"].strip()) <= 120:
        raise ValueError("Turniername muss 1 bis 120 Zeichen haben")
    dates = payload.get("round_dates")
    if not isinstance(dates, list) or len(dates) != payload["parsed"]["rounds"]:
        raise ValueError("Für jede Runde wird ein Datum benötigt")
    for d in dates:
        try:
            parsed = date.fromisoformat(d)
        except (ValueError, TypeError):
            raise ValueError("Ungültiges Rundendatum")
        if parsed.isoformat() != d or parsed > date.today():
            raise ValueError("Rundendatum muss gültig sein und darf nicht in der Zukunft liegen")
    if dates != sorted(dates):
        raise ValueError("Rundendaten müssen chronologisch sein")


def import_tournament(db, payload, owner):
    validate_payload(payload)
    category = payload["category"]
    mapping = payload.get("mapping", {})
    if not isinstance(mapping, dict):
        raise ValueError("Spielerzuordnung ungültig")
    ids, used = {}, set()
    for p in payload["parsed"]["players"]:
        key = normalize(p["name"])
        alias = db.execute("SELECT player_id FROM aliases WHERE name_key=?", (key,)).fetchone()
        chosen = mapping.get(str(p["number"]))
        if chosen not in (None, "", 0, "0"):
            try:
                chosen = int(chosen)
            except (ValueError, TypeError):
                raise ValueError("Ungültige Spielerzuordnung")
            if not db.execute("SELECT id FROM players WHERE id=?", (chosen,)).fetchone():
                raise ValueError("Zugeordneter Spieler existiert nicht")
            if alias and alias[0] != chosen:
                raise ValueError(f"{p['name']} ist bereits einem anderen Spieler zugeordnet")
        else:
            chosen = alias[0] if alias else None
        if chosen is None:
            chosen = db.execute("INSERT INTO players(name,created) VALUES(?,?)", (p["name"], time.time())).lastrowid
        if chosen in used:
            raise ValueError("Zwei Turnierteilnehmer dürfen nicht demselben Spieler zugeordnet sein")
        used.add(chosen)
        ids[p["number"]] = chosen
        db.execute("INSERT OR IGNORE INTO aliases(name_key,name,player_id) VALUES(?,?,?)", (key, p["name"], chosen))
    games = [{**g, "white": ids[g["white"]], "black": ids[g["black"]]} for g in payload["parsed"]["games"]]
    dates = payload["round_dates"]
    # Normalize row ordering and ignore filename/title for duplicate detection.
    canonical = {"category": category, "dates": dates,
                 "games": sorted(games, key=lambda g: (g["round"], g["white"], g["black"]))}
    fingerprint = hashlib.sha256(json.dumps(canonical, sort_keys=True).encode()).hexdigest()
    raw_hash = hashlib.sha256(payload["text"].encode()).hexdigest()
    if db.execute("SELECT id FROM tournaments WHERE active=1 AND (fingerprint=? OR (raw_hash=? AND category=?))",
                  (fingerprint, raw_hash, category)).fetchone():
        raise ValueError("Dieses Turnier wurde bereits importiert. Für eine Korrektur zuerst zurücknehmen.")
    # Interleaving multi-day events needs actual timing not available from a TRF.
    for old in db.execute("SELECT date,end_date FROM tournaments WHERE active=1 AND category=?", (category,)):
        overlap = dates[0] <= old["end_date"] and dates[-1] >= old["date"]
        if overlap and (dates[0] != dates[-1] or old["date"] != old["end_date"]):
            raise ValueError("Überlappende mehrtägige Turniere derselben Kategorie benötigen eindeutige Partiezeiten")
    # A corrected reimport of the same named event retains its chronology slot.
    previous = db.execute("""SELECT sequence FROM tournaments WHERE active=0 AND name=? AND category=? AND date=?
                             ORDER BY id DESC LIMIT 1""", (payload['name'].strip(), category, dates[0])).fetchone()
    sequence = previous[0] if previous else db.execute('SELECT COALESCE(MAX(sequence),0)+1 FROM tournaments').fetchone()[0]
    if db.execute('SELECT 1 FROM tournaments WHERE active=1 AND sequence=?', (sequence,)).fetchone():
        sequence = db.execute('SELECT COALESCE(MAX(sequence),0)+1 FROM tournaments').fetchone()[0]
    tid = db.execute("""INSERT INTO tournaments(name,category,date,end_date,imported,owner,filename,original,
                      raw_hash,fingerprint,engine,round_dates,skipped,sequence) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                     (payload["name"].strip(), category, dates[0], dates[-1], time.time(), owner,
                      payload["filename"], payload["text"], raw_hash, fingerprint, ENGINE_VERSION,
                      json.dumps(dates), json.dumps(payload["parsed"]["skipped"]), sequence)).lastrowid
    for g in games:
        db.execute("INSERT INTO games(tournament_id,round,white,black,score,played) VALUES(?,?,?,?,?,?)",
                   (tid, g["round"], g["white"], g["black"], g["score"], timestamp(dates[g["round"] - 1])))
    rebuild(db)
    return tid


def rebuild(db):
    """Replay from initial values, sorted by tournament date, id, then round.

    No destructive changes to source events. Only materialized ratings/history
    are replaced in the enclosing transaction.
    """
    db.execute("DELETE FROM history")
    db.execute("DELETE FROM ratings")
    state = {}
    for g in db.execute("""SELECT g.*,t.category FROM games g JOIN tournaments t ON t.id=g.tournament_id
                            WHERE t.active=1 ORDER BY t.date,t.sequence,t.id,g.round,g.id"""):
        cat = g["category"]
        wkey, bkey = (g["white"], cat), (g["black"], cat)
        w, b = state.get(wkey, Rating()), state.get(bkey, Rating())
        nw, nb = game(w, b, g["score"], cat, g["played"])
        for pid, before, after in ((g["white"], live(w, g["played"]), nw), (g["black"], live(b, g["played"]), nb)):
            db.execute("INSERT INTO history(game_id,player_id,before,after) VALUES(?,?,?,?)",
                       (g["id"], pid, json.dumps(before.json()), json.dumps(after.json())))
        state[wkey], state[bkey] = nw, nb
    for p in db.execute("SELECT id FROM players"):
        for cat in ("blitz", "rapid"):
            r = state.get((p["id"], cat), Rating())
            db.execute("INSERT INTO ratings VALUES(?,?,?,?,?,?,?)",
                       (p["id"], cat, r.rating, r.rd, r.volatility, r.games, r.latest))


def rating_from_row(row):
    return Rating(row["rating"], row["rd"], row["volatility"], row["games"], row["latest"])


def ranking(db, category, at=None):
    at = time.time() if at is None else at
    rows = []
    for p in db.execute("""SELECT p.id,p.name,r.* FROM players p JOIN ratings r ON r.player_id=p.id
                           WHERE r.category=? ORDER BY r.rating DESC,p.name""", (category,)):
        r = live(rating_from_row(p), at)
        hist = db.execute("""SELECT h.before,h.after FROM history h JOIN games g ON g.id=h.game_id
                            JOIN tournaments t ON t.id=g.tournament_id WHERE h.player_id=? AND t.category=?
                            ORDER BY t.date DESC,t.sequence DESC,t.id DESC,g.round DESC,g.id DESC LIMIT 1""", (p["id"], category)).fetchone()
        diff = int(json.loads(hist["after"])["rating"]) - int(json.loads(hist["before"])["rating"]) if hist else 0
        rows.append({"id": p["id"], "name": p["name"], **r.json(), "display": int(r.rating),
                     "provisional": r.rd >= 110, "rankable": r.rd <= 75, "diff": diff})
    return rows


def tournament_detail(db, tid):
    t = db.execute("""SELECT t.*,u.username FROM tournaments t JOIN users u ON u.id=t.owner
                       WHERE t.id=?""", (tid,)).fetchone()
    if not t:
        raise ValueError("Turnier nicht gefunden")
    changes = {}
    games = []
    for g in db.execute("""SELECT g.*,w.name white_name,b.name black_name FROM games g
                           JOIN players w ON w.id=g.white JOIN players b ON b.id=g.black
                           WHERE tournament_id=? ORDER BY round,g.id""", (tid,)):
        entry = dict(g)
        for side in ("white", "black"):
            h = db.execute("SELECT before,after FROM history WHERE game_id=? AND player_id=?", (g["id"], g[side])).fetchone()
            if h:
                before, after = json.loads(h["before"]), json.loads(h["after"])
                entry[side + "_diff"] = int(after["rating"]) - int(before["rating"])
                if g[side] not in changes:
                    changes[g[side]] = {"id": g[side], "name": g[side + "_name"], "before": int(before["rating"]), "games": 0}
                changes[g[side]].update(after=int(after["rating"]), rd=after["rd"])
                changes[g[side]]["games"] += 1
        games.append(entry)
    for c in changes.values():
        c["diff"] = c["after"] - c["before"]
    return {"id": tid, "name": t["name"], "category": t["category"], "date": t["date"],
            "end_date": t["end_date"], "active": bool(t["active"]), "owner": t["owner"],
            "director": t["username"], "engine": t["engine"], "games": games,
            "changes": sorted(changes.values(), key=lambda c: -c["after"]),
            "skipped": json.loads(t["skipped"]), "round_dates": json.loads(t["round_dates"])}
