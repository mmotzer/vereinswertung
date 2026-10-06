"""Local setup and offline database recovery. Never prints passwords/tokens."""

import argparse
import getpass
import os
import secrets
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

from app import ROOT, backup_database, load_env
from vereinswertung import storage


def main():
    parser = argparse.ArgumentParser(description="Vereinswertung verwalten")
    parser.add_argument(
        "command", choices=["init-local", "backup", "restore", "reset-admin"]
    )
    parser.add_argument("--file", help="Sicherungsdatei für restore")
    parser.add_argument("--username", help="Administrator für reset-admin")
    args = parser.parse_args()
    if args.command == "init-local":
        path = ROOT / ".env"
        if path.exists():
            raise SystemExit(".env existiert bereits; nicht überschrieben.")
        path.write_text(
            f"BOOTSTRAP_TOKEN={secrets.token_urlsafe(32)}\nSECURE_COOKIE=false\nHOST=127.0.0.1\nPORT=8080\n",
            encoding="utf-8",
        )
        print(
            "Lokale Konfiguration erstellt. Einrichtungsschlüssel steht in .env."
        )
        return
    load_env()
    database = Path(
        os.environ.get("DATABASE", str(ROOT / "data" / "club.sqlite"))
    ).resolve()
    if args.command == "backup":
        if not database.exists():
            raise SystemExit("Datenbank fehlt")
        print(backup_database(str(database)))
    elif args.command == "restore":
        if not args.file:
            raise SystemExit("--file angeben. App muss vorher gestoppt sein.")
        source = Path(args.file).resolve()
        if not source.is_file() or source == database:
            raise SystemExit("Sicherungsdatei ungültig")
        with closing(
            sqlite3.connect(f"{source.as_uri()}?mode=ro", uri=True)
        ) as candidate:
            if (
                candidate.execute("PRAGMA integrity_check").fetchone()[0]
                != "ok"
            ):
                raise SystemExit("Sicherung ist beschädigt")
            if candidate.execute("PRAGMA foreign_key_check").fetchall():
                raise SystemExit("Sicherung enthält ungültige Beziehungen")
            tables = {
                r[0]
                for r in candidate.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            if (
                not {
                    "players",
                    "tournaments",
                    "ratings",
                    "games",
                    "history",
                    "users",
                    "meta",
                    "audit",
                    "sessions",
                    "previews",
                }
                <= tables
            ):
                raise SystemExit("Keine passende Vereinswertung-Sicherung")
        if (
            input("App gestoppt? Zum Wiederherstellen RESTORE eingeben: ")
            != "RESTORE"
        ):
            raise SystemExit("Abgebrochen")
        database.parent.mkdir(parents=True, exist_ok=True)
        if database.exists():
            backup_database(str(database))
        temp = database.with_suffix(".restore.sqlite")
        shutil.copyfile(source, temp)
        # Existing sidecars must not be replayed into the restored database.
        for suffix in ("-wal", "-shm"):
            sidecar = Path(str(database) + suffix)
            if sidecar.exists():
                sidecar.unlink()
        os.replace(temp, database)
        with storage.open_db(str(database)) as db:
            db.execute("DELETE FROM sessions")
            db.execute("DELETE FROM previews")
        print(
            "Datenbank wiederhergestellt. Alle Benutzer müssen sich neu anmelden."
        )
    else:
        if not args.username or not database.exists():
            raise SystemExit("Vorhandene Datenbank und --username benötigt")
        pw = getpass.getpass("Neues Administratorpasswort (mind. 12 Zeichen): ")
        if not 12 <= len(pw) <= 200 or pw != getpass.getpass(
            "Passwort wiederholen: "
        ):
            raise SystemExit("Passwörter ungültig oder unterschiedlich")
        from werkzeug.security import generate_password_hash

        with storage.open_db(str(database)) as db:
            u = db.execute(
                "SELECT id FROM users WHERE username=? AND role='admin'",
                (args.username,),
            ).fetchone()
            if not u:
                raise SystemExit("Administrator nicht gefunden")
            db.execute(
                "UPDATE users SET password=?,active=1 WHERE id=?",
                (generate_password_hash(pw), u[0]),
            )
            db.execute("DELETE FROM sessions WHERE user_id=?", (u[0],))
            storage.audit(
                db,
                u[0],
                "offline_reset",
                "Administratorzugang lokal wiederhergestellt",
            )
        print("Administratorzugang wiederhergestellt")


if __name__ == "__main__":
    main()
