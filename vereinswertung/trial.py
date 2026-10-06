"""Anonymous one-off rating simulation; input exists only in a temporary folder."""

import base64
import binascii
import tempfile
import threading
from pathlib import Path

from vereinswertung import storage, trf

MAX_BYTES = 1024 * 1024
SLOTS = threading.BoundedSemaphore(2)


def _calculate(data, sample_file):
    if not isinstance(data, dict):
        raise ValueError("Ungültige Anfrage")
    if data.get("sample") is True:
        raw = Path(sample_file).read_bytes()
    else:
        content = data.get("content")
        if (
            not isinstance(content, str)
            or len(content) > ((MAX_BYTES + 2) // 3) * 4
        ):
            raise ValueError("TRF-Datei darf höchstens 1 MB groß sein")
        try:
            raw = base64.b64decode(content, validate=True)
        except (binascii.Error, ValueError):
            raise ValueError("Datei ungültig")
    if not raw or len(raw) > MAX_BYTES:
        raise ValueError("TRF-Datei muss zwischen 1 Byte und 1 MB groß sein")
    text = trf.decode(raw)
    parsed = trf.parse(text)
    if (
        len(parsed["players"]) > 200
        or len(parsed["games"]) > 2000
        or parsed["rounds"] > 30
    ):
        raise ValueError(
            "Der Probeimport unterstützt höchstens 200 Spieler, 2000 Partien und 30 Runden"
        )
    dates = data.get("round_dates")
    if dates is None:
        if parsed["end_date"] and parsed["end_date"] != parsed["date"]:
            raise ValueError(
                "Für dieses mehrtägige Turnier die Datumsprüfung öffnen und jeder Runde ein Datum zuordnen"
            )
        dates = [data.get("day") or parsed["date"]] * parsed["rounds"]
    payload = dict(
        text=text,
        parsed=parsed,
        filename="Probeimport.trf",
        name=parsed["name"],
        category=data.get("category", "blitz"),
        round_dates=dates,
        mapping={},
    )
    storage.validate_payload(payload)
    with tempfile.TemporaryDirectory(prefix="vereinswertung-trial-") as folder:
        database = Path(folder) / "preview.sqlite"
        storage.initialize(database)
        with storage.open_db(database) as db:
            db.execute(
                "INSERT INTO users(username,password,role,created) VALUES('demo','!disabled','admin',0)"
            )
            tid = storage.import_tournament(db, payload, 1)
            rows = storage.ranking(db, payload["category"])
            detail = storage.tournament_detail(db, tid)
            return dict(
                name=parsed["name"],
                category=payload["category"],
                rounds=parsed["rounds"],
                games=len(parsed["games"]),
                players=[
                    dict(
                        name=row["name"],
                        rating=row["display"],
                        games=row["games"],
                        change=row["display"] - 1500,
                        provisional=row["provisional"],
                    )
                    for row in rows
                    if row["games"]
                ],
                changes=detail["changes"],
                warnings=parsed["warnings"],
                skipped=parsed["skipped"],
                initial_rating=1500,
                persisted=False,
                round_dates=dates,
            )


def calculate(data, sample_file):
    if not SLOTS.acquire(blocking=False):
        from werkzeug.exceptions import TooManyRequests

        raise TooManyRequests(
            "Probeimport ausgelastet. Bitte kurz erneut versuchen."
        )
    try:
        return _calculate(data, sample_file)
    finally:
        SLOTS.release()
