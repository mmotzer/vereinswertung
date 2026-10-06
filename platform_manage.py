"""Operator-only local CLI: migration snapshots and complete platform backups."""
import argparse
import re
import secrets
import sqlite3
import time
from contextlib import closing
from pathlib import Path

from club_platform import create_platform


def backup_platform(app):
    root=Path(app.config['DATA_ROOT']).resolve()
    target=root/'backups'/(time.strftime('%Y%m%d-%H%M%S',time.gmtime())+'-'+secrets.token_hex(3))
    target.mkdir(parents=True)
    # Registry and each SQLite database are independently consistent snapshots.
    # Pause registrations/billing for a coordinated full restore point.
    with closing(sqlite3.connect(root/'platform.sqlite')) as source, closing(sqlite3.connect(target/'platform.sqlite')) as destination:source.backup(destination)
    with closing(sqlite3.connect(target/'platform.sqlite')) as registry:
        ids=[row[0] for row in registry.execute('SELECT id FROM clubs WHERE provisioned=1')]
    for cid in ids:
        if not re.fullmatch(r'[a-f0-9]{32}',cid):raise ValueError('Ungültige Vereinskennung')
        file=root/'tenants'/cid/'club.sqlite'
        if not file.is_file():raise ValueError('Vereinsdatenbank fehlt: '+cid)
        folder=target/'tenants'/cid;folder.mkdir(parents=True)
        with closing(sqlite3.connect(file)) as source,closing(sqlite3.connect(folder/'club.sqlite')) as destination:source.backup(destination)
    return target


def import_club(app,file,slug,name,email,username):
    """Copy an existing club; never alter the source. Explicitly invalidate sessions."""
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{2,39}',slug):raise ValueError('Ungültiges Vereinskürzel')
    if not file.is_file():raise ValueError('Datenbank fehlt')
    registry=app.extensions['registry']
    with registry() as db:
        if db.execute('SELECT 1 FROM clubs WHERE slug=?',(slug,)).fetchone():raise ValueError('Verein existiert bereits')
    with closing(sqlite3.connect(file.as_uri()+'?mode=ro',uri=True)) as source:
        administrator=source.execute("SELECT password FROM users WHERE username=? AND role='admin' AND active=1",(username,)).fetchone()
        if not administrator:raise ValueError('Aktiver Administrator fehlt')
        cid=secrets.token_hex(16);folder=Path(app.config['DATA_ROOT'])/'tenants'/cid;folder.mkdir(parents=True)
        with closing(sqlite3.connect(folder/'club.sqlite')) as destination:
            source.backup(destination)
            with destination:destination.execute('DELETE FROM sessions')
    with registry() as db:
        db.execute('INSERT INTO clubs(id,slug,name,email,username,password,status,plan,created,provisioned) VALUES(?,?,?,?,?,?,?,?,?,1)',
            (cid,slug,name,email,username,administrator[0],'active','legacy',time.time()))
    return '/v/'+slug+'/'


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--data',required=True)
    commands=parser.add_subparsers(dest='command',required=True)
    commands.add_parser('backup')
    migrate=commands.add_parser('import-club')
    for name in ('file','slug','name','email','admin'):migrate.add_argument('--'+name,required=True)
    args=parser.parse_args();app=create_platform(dict(DATA_ROOT=args.data))
    if args.command=='backup':print(backup_platform(app))
    else:print(import_club(app,Path(args.file).resolve(),args.slug,args.name,args.email,args.admin))


if __name__=='__main__':main()
