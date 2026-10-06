"""Idempotent provisioning from a private deployment roster. No external ratings are read."""
import json
import re
import time
import unicodedata
import sqlite3
from contextlib import closing
from pathlib import Path
from vereinswertung import storage
def name_keys(name):
    name=name.casefold().replace('ß','ss')
    alternatives=[name,name.replace('ä','ae').replace('ö','oe').replace('ü','ue')]
    return {re.sub(r'[^a-z0-9]','', ''.join(c for c in unicodedata.normalize('NFKD',n) if not unicodedata.combining(c))) for n in alternatives}


def provision(db,entries):
    for entry in entries:
        name,number=entry['name'],entry['club_number']
        old=db.execute('SELECT player_id FROM club_members WHERE club_number=?',(number,)).fetchone()
        if old:
            continue
        keys=name_keys(name)
        candidates={row['id'] for row in db.execute('SELECT id,name FROM players') if keys & name_keys(row['name'])}
        candidates.update(row['player_id'] for row in db.execute('SELECT player_id,name FROM aliases') if keys & name_keys(row['name']))
        if len(candidates)>1:
            raise ValueError('Mehrdeutige Spielerzuordnung für '+name)
        if candidates:
            pid=candidates.pop()
            db.execute('UPDATE players SET name=? WHERE id=?',(name,pid))
        else:
            pid=db.execute('INSERT INTO players(name,created) VALUES(?,?)',(name,time.time())).lastrowid
        alias=storage.normalize(name)
        db.execute('INSERT OR IGNORE INTO aliases VALUES(?,?,?)',(alias,name,pid))
        if db.execute('SELECT 1 FROM club_members WHERE player_id=?',(pid,)).fetchone():
            raise ValueError('Spieler wurde mehrfach in der Vereinsliste aufgeführt: '+name)
        username='mitglied-'+number
        if db.execute('SELECT 1 FROM users WHERE username=?',(username,)).fetchone():
            raise ValueError('Reservierter Benutzername bereits vergeben: '+username)
        uid=db.execute("INSERT INTO users(username,password,role,active,created) VALUES(?,'!unclaimed','member',0,?)",(username,time.time())).lastrowid
        db.execute('INSERT INTO club_members(player_id,user_id,club_number) VALUES(?,?,?)',(pid,uid,number))
    # New profiles get initial values; existing game-derived ratings are replayed unchanged.
    storage.rebuild(db)


def from_file(path,database):
    if not path.is_file(): return
    entries=json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(entries,list) or not entries:
        raise ValueError('Vereinsliste muss eine nicht leere Liste sein')
    numbers=set()
    for entry in entries:
        if not isinstance(entry,dict) or not isinstance(entry.get('name'),str) or not entry['name'].strip() or not isinstance(entry.get('club_number'),str) or not re.fullmatch(r'[0-9]{4}',entry['club_number']) or entry['club_number'] in numbers:
            raise ValueError('Ungültiger oder doppelter Eintrag in der Vereinsliste')
        numbers.add(entry['club_number'])
    with storage.open_db(database) as db:
        missing=[entry for entry in entries if not db.execute('SELECT 1 FROM club_members WHERE club_number=?',(entry['club_number'],)).fetchone()]
        if missing:
            backup=Path(database).parent/'backups'/('before-roster-'+str(time.time_ns())+'.sqlite')
            backup.parent.mkdir(exist_ok=True)
            with closing(sqlite3.connect(backup)) as snapshot:
                db.backup(snapshot)
            provision(db,missing)
            storage.bump(db)
            print(f'Vereinskonten vorbereitet: {len(missing)}; bestehende Spielerzuordnungen erhalten.',flush=True)
