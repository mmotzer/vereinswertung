"""Operator-only local CLI: migration snapshots and complete platform backups."""

import argparse
import hashlib
import json
import re
import secrets
import sqlite3
import time
from contextlib import closing
from pathlib import Path

from club_platform import create_platform


def backup_platform(app):
    root = Path(app.config["DATA_ROOT"]).resolve()
    target = (
        root
        / "backups"
        / (
            time.strftime("%Y%m%d-%H%M%S", time.gmtime())
            + "-"
            + secrets.token_hex(3)
        )
    )
    target.mkdir(parents=True)
    # Registry and each SQLite database are independently consistent snapshots.
    # Pause registrations/billing for a coordinated full restore point.
    with (
        closing(sqlite3.connect(root / "platform.sqlite")) as source,
        closing(sqlite3.connect(target / "platform.sqlite")) as destination,
    ):
        source.backup(destination)
    with closing(sqlite3.connect(target / "platform.sqlite")) as registry:
        ids = [
            row[0]
            for row in registry.execute(
                "SELECT id FROM clubs WHERE provisioned=1"
            )
        ]
    for cid in ids:
        if not re.fullmatch(r"[a-f0-9]{32}", cid):
            raise ValueError("Ungültige Vereinskennung")
        file = root / "tenants" / cid / "club.sqlite"
        if not file.is_file():
            raise ValueError("Vereinsdatenbank fehlt: " + cid)
        folder = target / "tenants" / cid
        folder.mkdir(parents=True)
        with (
            closing(sqlite3.connect(file)) as source,
            closing(sqlite3.connect(folder / "club.sqlite")) as destination,
        ):
            source.backup(destination)
    files = ["platform.sqlite"] + [
        "tenants/" + cid + "/club.sqlite" for cid in ids
    ]
    marker = target / "complete.tmp"
    marker.write_text(
        json.dumps(
            dict(
                version=1,
                clubs=ids,
                files={name: file_digest(target / name) for name in files},
            )
        ),
        encoding="utf-8",
    )
    marker.replace(target / "complete.json")
    return target


def file_digest(file):
    digest = hashlib.sha256()
    with open(file, "rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_backup(snapshot):
    snapshot = Path(snapshot).resolve()
    manifest = json.loads(
        (snapshot / "complete.json").read_text(encoding="utf-8")
    )
    ids = manifest.get("clubs")
    if (
        manifest.get("version") != 1
        or not isinstance(ids, list)
        or any(
            not isinstance(cid, str) or not re.fullmatch(r"[a-f0-9]{32}", cid)
            for cid in ids
        )
    ):
        raise ValueError("Ungültige Sicherung")
    expected = {"platform.sqlite"} | {
        "tenants/" + cid + "/club.sqlite" for cid in ids
    }
    if set(manifest.get("files", {})) != expected:
        raise ValueError("Unvollständige Sicherung")
    for name, digest in manifest["files"].items():
        if (
            not (snapshot / name).resolve().is_relative_to(snapshot)
            or (snapshot / name).is_symlink()
            or file_digest(snapshot / name) != digest
        ):
            raise ValueError("Sicherung beschädigt: " + name)
        with closing(
            sqlite3.connect((snapshot / name).as_uri() + "?mode=ro", uri=True)
        ) as db:
            if (
                db.execute("PRAGMA foreign_key_check").fetchone()
                or db.execute("PRAGMA integrity_check").fetchone()[0] != "ok"
            ):
                raise ValueError("Datenbank beschädigt: " + name)
    with closing(
        sqlite3.connect(
            (snapshot / "platform.sqlite").as_uri() + "?mode=ro", uri=True
        )
    ) as db:
        if {
            row[0]
            for row in db.execute("SELECT id FROM clubs WHERE provisioned=1")
        } != set(ids):
            raise ValueError(
                "Vereinsregister und Sicherungsdateien stimmen nicht überein"
            )
    return ids


def restore_backup(app, snapshot):
    """Restore into a fresh destination only; invalidate login tokens."""
    snapshot = Path(snapshot).resolve()
    ids = verify_backup(snapshot)
    root = Path(app.config["DATA_ROOT"]).resolve()
    if any(file.name != "platform.sqlite" for file in root.iterdir()):
        raise ValueError(
            "Wiederherstellung benötigt einen neuen, leeren Datenordner"
        )
    with app.extensions["registry"]() as db:
        if db.execute("SELECT COUNT(*) FROM clubs").fetchone()[0]:
            raise ValueError("Ziel enthält bereits Vereine")
    for cid in ids:
        folder = root / "tenants" / cid
        folder.mkdir(parents=True)
        with (
            closing(
                sqlite3.connect(
                    (snapshot / "tenants" / cid / "club.sqlite").as_uri()
                    + "?mode=ro",
                    uri=True,
                )
            ) as source,
            closing(sqlite3.connect(folder / "club.sqlite")) as destination,
        ):
            source.backup(destination)
            with destination:
                destination.execute("DELETE FROM sessions")
                destination.execute("DELETE FROM previews")
    with (
        closing(
            sqlite3.connect(
                (snapshot / "platform.sqlite").as_uri() + "?mode=ro", uri=True
            )
        ) as source,
        closing(sqlite3.connect(root / "platform.sqlite")) as destination,
    ):
        source.backup(destination)
        with destination:
            destination.execute(
                "UPDATE clubs SET status='suspended' WHERE subscription IS NOT NULL"
            )
    return root


def import_club(app, file, slug, name, email, username):
    """Copy an existing club; never alter the source. Explicitly invalidate sessions."""
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,39}", slug):
        raise ValueError("Ungültiges Vereinskürzel")
    if not file.is_file():
        raise ValueError("Datenbank fehlt")
    registry = app.extensions["registry"]
    with registry() as db:
        if db.execute("SELECT 1 FROM clubs WHERE slug=?", (slug,)).fetchone():
            raise ValueError("Verein existiert bereits")
    with closing(
        sqlite3.connect(file.as_uri() + "?mode=ro", uri=True)
    ) as source:
        administrator = source.execute(
            "SELECT password FROM users WHERE username=? AND role='admin' AND active=1",
            (username,),
        ).fetchone()
        if not administrator:
            raise ValueError("Aktiver Administrator fehlt")
        cid = secrets.token_hex(16)
        folder = Path(app.config["DATA_ROOT"]) / "tenants" / cid
        folder.mkdir(parents=True)
        with closing(sqlite3.connect(folder / "club.sqlite")) as destination:
            source.backup(destination)
            with destination:
                destination.execute("DELETE FROM sessions")
    with registry() as db:
        db.execute(
            "INSERT INTO clubs(id,slug,name,email,username,password,status,plan,created,provisioned) VALUES(?,?,?,?,?,?,?,?,?,1)",
            (
                cid,
                slug,
                name,
                email,
                username,
                administrator[0],
                "active",
                "legacy",
                time.time(),
            ),
        )
    return "/v/" + slug + "/"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("backup")
    commands.add_parser("sync-billing")
    verify = commands.add_parser("verify-backup")
    verify.add_argument("--snapshot", required=True)
    restore = commands.add_parser("restore")
    restore.add_argument("--snapshot", required=True)
    migrate = commands.add_parser("import-club")
    for name in ("file", "slug", "name", "email", "admin"):
        migrate.add_argument("--" + name, required=True)
    args = parser.parse_args()
    app = create_platform(dict(DATA_ROOT=args.data))
    if args.command == "backup":
        print(backup_platform(app))
    elif args.command == "sync-billing":
        print("Abos abgeglichen:", app.extensions["sync_billing"]())
    elif args.command == "verify-backup":
        print("Geprüfte Vereinsdatenbanken:", len(verify_backup(args.snapshot)))
    elif args.command == "restore":
        print(restore_backup(app, args.snapshot))
    else:
        print(
            import_club(
                app,
                Path(args.file).resolve(),
                args.slug,
                args.name,
                args.email,
                args.admin,
            )
        )


if __name__ == "__main__":
    main()
