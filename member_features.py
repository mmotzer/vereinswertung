"""Member submissions never change ratings; directors review through the normal importer."""
import json
import re
import time
import hashlib
import secrets
from datetime import date, datetime
from zoneinfo import ZoneInfo
from flask import g, jsonify
import storage


def request_email(db, fallback=''):
    row = db.execute("SELECT value FROM settings WHERE key='request_email'").fetchone()
    return row[0] if row else fallback


def validate_submission(data,db):
    if data.get('consent') is not True:
        raise ValueError('Die vor der Partie vereinbarte Zustimmung beider Spieler bestätigen')
    note = data.get('note','')
    if not isinstance(note,str) or len(note)>1000:
        raise ValueError('Hinweis darf höchstens 1000 Zeichen haben')
    if data.get('mode') == 'match':
        first_id,second_id,day = data.get('first_player'),data.get('second_player'),data.get('day')
        if not isinstance(first_id,int) or not isinstance(second_id,int) or first_id==second_id:
            raise ValueError('Zwei verschiedene Vereinsspieler auswählen')
        first=db.execute('SELECT username FROM lichess_accounts WHERE player_id=?',(first_id,)).fetchone()
        second=db.execute('SELECT username FROM lichess_accounts WHERE player_id=?',(second_id,)).fetchone()
        if not first or not second:
            raise ValueError('Für beide Spieler muss die Turnierleitung zuerst einen Lichess-Namen hinterlegen')
        try:
            if date.fromisoformat(day)>datetime.now(ZoneInfo("Europe/Berlin")).date():
                raise ValueError()
        except (TypeError,ValueError):
            raise ValueError('Gültigen Spieltag auswählen, nicht in der Zukunft')
        payload={'mode':'match','first':first[0],'second':second[0],'first_player':first_id,'second_player':second_id,'day':day}
    else:
        raise ValueError('Spieltag und zwei Vereinsspieler auswählen')
    return {**payload,'consent':True},note.strip()


def register(app,db,fields,admin,director,is_director,check_limit,credentials,client_address,hash_password):
    @app.post('/api/invitations')
    def invitation():
        admin()
        check_limit('invitations:'+str(g.user['id']),20)
        code=secrets.token_urlsafe(24)
        expires=time.time()+7*86400
        with db():
            iid=db().execute('INSERT INTO invitations(code_hash,created_by,created,expires) VALUES(?,?,?,?)',
                (hashlib.sha256(code.encode()).hexdigest(),g.user['id'],time.time(),expires)).lastrowid
            storage.audit(db(),g.user['id'],'invite_create',f'Mitgliedercode {iid} erstellt')
        return jsonify(code=code,expires=expires)

    @app.post('/api/register')
    def register_member():
        check_limit('register:'+client_address(),10)
        data=fields()
        code=data.get('code')
        if not isinstance(code,str) or not 20<=len(code.strip())<=100:
            raise ValueError('Gültigen Registrierungscode eingeben')
        username,password=credentials(data)
        hashed=hashlib.sha256(code.strip().encode()).hexdigest()
        if not db().execute('SELECT 1 FROM invitations WHERE code_hash=? AND used_by IS NULL AND expires>?',(hashed,time.time())).fetchone():
            raise ValueError('Code ungültig, abgelaufen oder bereits verwendet')
        # Hash the password before taking the database write lock.
        password_hash=hash_password(password)
        db().execute('BEGIN IMMEDIATE')
        try:
            invite=db().execute('SELECT id FROM invitations WHERE code_hash=? AND used_by IS NULL AND expires>?',(hashed,time.time())).fetchone()
            if not invite:
                raise ValueError('Code ungültig, abgelaufen oder bereits verwendet')
            uid=db().execute("INSERT INTO users(username,password,role,created) VALUES(?,?,'member',?)",(username,password_hash,time.time())).lastrowid
            db().execute('UPDATE invitations SET used_by=?,used=? WHERE id=?',(uid,time.time(),invite['id']))
            storage.audit(db(),uid,'member_register',f'Mitgliedercode {invite["id"]} eingelöst')
            db().commit()
        except Exception:
            db().rollback()
            raise
        return jsonify(ok=True)
    @app.get('/api/submission-players')
    def submission_players():
        rows=db().execute('SELECT p.id,p.name,a.username FROM players p LEFT JOIN lichess_accounts a ON a.player_id=p.id ORDER BY p.name')
        return jsonify(players=[{'id':r['id'],'name':r['name'],'available':bool(r['username']),**({'username':r['username']} if is_director() else {})} for r in rows])

    @app.post('/api/players/<int:pid>/lichess')
    def set_lichess(pid):
        director()
        name=fields().get('username')
        if not isinstance(name,str) or not re.fullmatch(r'[A-Za-z0-9_-]{2,30}',name):
            raise ValueError('Gültigen Lichess-Namen eingeben')
        if not db().execute('SELECT id FROM players WHERE id=?',(pid,)).fetchone():
            raise ValueError('Spieler nicht gefunden')
        alias=db().execute('SELECT player_id FROM aliases WHERE name_key=?',(storage.normalize('Lichess: '+name),)).fetchone()
        if alias and alias[0]!=pid:
            raise ValueError('Dieses Lichess-Konto gehört bereits zu einem anderen Vereinsspieler')
        with db():
            db().execute('INSERT INTO lichess_accounts VALUES(?,?) ON CONFLICT(player_id) DO UPDATE SET username=excluded.username',(pid,name))
            storage.audit(db(),g.user['id'],'lichess_account',f'Lichess-Konto für Spieler {pid} hinterlegt')
        return jsonify(ok=True)
    @app.get('/api/settings')
    def settings():
        admin()
        return jsonify(request_email=request_email(db(),app.config['REQUEST_EMAIL']))

    @app.post('/api/settings')
    def save_settings():
        admin()
        email=fields().get('request_email','')
        if not isinstance(email,str) or len(email)>254 or (email and not re.fullmatch(r'[A-Za-z0-9.!#$%&\'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}',email)):
            raise ValueError('Gültige E-Mail-Adresse eingeben')
        with db():
            db().execute("INSERT INTO settings VALUES('request_email',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(email,))
            storage.audit(db(),g.user['id'],'settings','Adresse für Zugangsanfragen geändert')
        return jsonify(ok=True)

    @app.get('/api/submissions')
    def submissions():
        rows=db().execute("""SELECT s.*,u.username FROM submissions s JOIN users u ON u.id=s.owner
            WHERE (? OR s.owner=?) ORDER BY CASE WHEN s.status='pending' THEN 0 ELSE 1 END,s.created DESC LIMIT 200""",(is_director(),g.user['id']))
        result=[]
        for r in rows:
            payload=json.loads(r['payload'])
            if not is_director():
                payload={k:v for k,v in payload.items() if k in ('mode','first_player','second_player','day','consent')}
            result.append({**dict(r),'payload':payload})
        return jsonify(submissions=result)

    @app.post('/api/submissions')
    def submit():
        check_limit('submission:'+str(g.user['id']),10)
        payload,note=validate_submission(fields(),db())
        encoded=json.dumps(payload,sort_keys=True)
        with db():
            if db().execute("SELECT 1 FROM submissions WHERE owner=? AND status='pending' AND payload=?",(g.user['id'],encoded)).fetchone():
                raise ValueError('Diese Einreichung wartet bereits auf Prüfung')
            sid=db().execute('INSERT INTO submissions(owner,created,payload,note) VALUES(?,?,?,?)',(g.user['id'],time.time(),encoded,note)).lastrowid
            storage.audit(db(),g.user['id'],'submit',f'Partien zur Prüfung eingereicht: {sid}')
        return jsonify(ok=True,id=sid)

    @app.post('/api/submissions/<int:sid>/reject')
    def reject(sid):
        director()
        reason=fields().get('reason','')
        if not isinstance(reason,str) or not 1<=len(reason.strip())<=1000:
            raise ValueError('Bitte eine kurze Begründung eingeben')
        with db():
            changed=db().execute("UPDATE submissions SET status='rejected',reviewer=?,reviewed=?,response=? WHERE id=? AND status='pending'",(g.user['id'],time.time(),reason.strip(),sid))
            if not changed.rowcount: raise ValueError('Einreichung ist nicht mehr offen')
            storage.audit(db(),g.user['id'],'reject_submission',f'Einreichung {sid} abgelehnt')
        return jsonify(ok=True)
