"""Multi-club gateway. Every club uses its own database and cookie path."""
import hashlib
import html
import ipaddress
import logging
import json
import os
import re
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlparse

from flask import Flask, jsonify, request, send_from_directory
from werkzeug.wrappers import Response
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.exceptions import HTTPException

from app import ROOT, create_app, backup_database
from vereinswertung import storage
from vereinswertung import billing
from vereinswertung import permissions
from vereinswertung import trial
SCHEMA='''CREATE TABLE IF NOT EXISTS clubs(
 id TEXT PRIMARY KEY,slug TEXT NOT NULL UNIQUE,name TEXT NOT NULL,email TEXT NOT NULL,
 username TEXT NOT NULL,password TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',
 plan TEXT NOT NULL,created REAL NOT NULL,checkout TEXT,customer TEXT,subscription TEXT,
 event_created INTEGER NOT NULL DEFAULT 0,provisioned INTEGER NOT NULL DEFAULT 0);
 CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY,created INTEGER NOT NULL);
 CREATE TABLE IF NOT EXISTS limits(address TEXT PRIMARY KEY,count INTEGER NOT NULL,expires REAL NOT NULL);'''


def create_platform(config=None):
    app=Flask('club-platform',static_folder=None)
    app.config.update(DATA_ROOT=os.environ.get('PLATFORM_DATA',str(ROOT/'data'/'platform')),
        PUBLIC_ORIGIN=os.environ.get('PUBLIC_ORIGIN','').rstrip('/'),SECURE_COOKIE=True,
        STRIPE_SECRET_KEY=os.environ.get('STRIPE_SECRET_KEY',''),
        STRIPE_WEBHOOK_SECRET=os.environ.get('STRIPE_WEBHOOK_SECRET',''),
        STRIPE_PRICE_MONTH=os.environ.get('STRIPE_PRICE_MONTH',''),
        STRIPE_PRICE_YEAR=os.environ.get('STRIPE_PRICE_YEAR',''),
        LEGAL_READY=os.environ.get('LEGAL_READY','false')=='true',
        LEGAL_DIR=os.environ.get('LEGAL_DIR',''),
        TENANT_DOMAIN=os.environ.get('TENANT_DOMAIN','').lower().strip(),
        TRUSTED_PROXY_IPS=os.environ.get('TRUSTED_PROXY_IPS',''),MAX_CONTENT_LENGTH=3*1024*1024)
    if config: app.config.update(config)
    tenant_domain=app.config['TENANT_DOMAIN']
    if tenant_domain:
        if not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?',tenant_domain) or '..' in tenant_domain or '.' not in tenant_domain:raise ValueError('Ungültige Vereinsdomain')
        public_host=urlparse(app.config['PUBLIC_ORIGIN']).hostname or ''
        if public_host.endswith('.'+tenant_domain):raise ValueError('Plattformadresse darf keinen Vereins-Unterbereich belegen')
    root=Path(app.config['DATA_ROOT']).resolve();root.mkdir(parents=True,exist_ok=True)
    @contextmanager
    def registry():
        db=sqlite3.connect(root/'platform.sqlite',timeout=30);db.row_factory=sqlite3.Row
        try:
            with db: yield db
        finally: db.close()
    with registry() as db: db.executescript(SCHEMA)
    apps={};lock=threading.Lock();billing_lock=threading.Lock()
    password_slots=threading.BoundedSemaphore(2)
    app.extensions['registry']=registry

    def ready():
        legal=Path(app.config['LEGAL_DIR']) if app.config['LEGAL_DIR'] else None
        return bool(app.config['LEGAL_READY'] and legal and all((legal/(name+'.html')).is_file() for name in ('terms','privacy','imprint')) and app.config['PUBLIC_ORIGIN'].startswith('https://') and all(app.config[k] for k in ('STRIPE_SECRET_KEY','STRIPE_WEBHOOK_SECRET','STRIPE_PRICE_MONTH','STRIPE_PRICE_YEAR')))

    def tenant(row):
        with lock:
            if row['id'] not in apps:
                if not re.fullmatch(r'[a-f0-9]{32}',row['id']): raise ValueError('Ungültige Vereinskennung')
                folder=root/'tenants'/row['id']; folder.mkdir(parents=True,exist_ok=True)
                child=create_app(dict(DATABASE=str(folder/'club.sqlite'),BOOTSTRAP_TOKEN=secrets.token_urlsafe(32),
                    SEED_ROSTER=False,REQUEST_EMAIL=row['email'],PUBLIC_ORIGIN=('https://'+row['slug']+'.'+tenant_domain) if tenant_domain else app.config['PUBLIC_ORIGIN'],SECURE_COOKIE=app.config['SECURE_COOKIE'],
                    TRUSTED_PROXY_IPS=app.config['TRUSTED_PROXY_IPS'],TESTING=app.config.get('TESTING',False)))
                if not row['provisioned']:
                    with storage.open_db(child.config['DATABASE']) as db:
                        # Retries after a process crash must not replace an existing administrator.
                        db.execute("INSERT OR IGNORE INTO users(username,password,role,active,created) VALUES(?,?,'admin',1,?)",(row['username'],row['password'],time.time()))
                    with registry() as db: db.execute('UPDATE clubs SET provisioned=1 WHERE id=?',(row['id'],))
                if len(apps)>=100: apps.pop(next(iter(apps)))
                apps[row['id']]=child
            return apps[row['id']]

    def current_club(slug):
        with registry() as db: return db.execute('SELECT * FROM clubs WHERE slug=?',(slug,)).fetchone()

    def password_work(function,*args):
        if not password_slots.acquire(blocking=False):
            from werkzeug.exceptions import TooManyRequests
            raise TooManyRequests('Registrierung ausgelastet. Bitte kurz warten.')
        try:return function(*args)
        finally:password_slots.release()

    def peer_address():
        peer=request.remote_addr or 'unknown'
        if peer in {p.strip() for p in app.config['TRUSTED_PROXY_IPS'].split(',')}:
            try:return str(ipaddress.ip_address(request.headers.get('CF-Connecting-IP','')))
            except ValueError:pass
        return peer

    def club_url(slug):
        return 'https://'+slug+'.'+tenant_domain+'/' if tenant_domain else app.config['PUBLIC_ORIGIN']+'/v/'+slug+'/'

    def host_club():
        host=request.host.split(':',1)[0].lower()
        if tenant_domain and host.endswith('.'+tenant_domain):
            slug=host[:-(len(tenant_domain)+1)]
            if re.fullmatch(r'[a-z0-9][a-z0-9-]{2,39}',slug):return slug
        return None

    @app.before_request
    def origin():
        slug=host_club()
        if request.method=='POST' and (slug or request.path!='/api/platform/webhook'):
            expected=club_url(slug).rstrip('/') if slug else app.config['PUBLIC_ORIGIN'] or request.host_url.rstrip('/')
            if request.headers.get('Origin')!=expected: return jsonify(error='Ungültiger Ursprung'),403
        if slug:
            return serve_club(slug,request.path.lstrip('/'),'',club_url(slug).rstrip('/'))

    @app.after_request
    def headers(response):
        response.headers['Cache-Control']='no-store'
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['X-Frame-Options']='DENY'
        response.headers['Referrer-Policy']='same-origin'
        response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
        if app.config['SECURE_COOKIE']:response.headers['Strict-Transport-Security']='max-age=31536000'
        return response

    @app.errorhandler(ValueError)
    def invalid(error): return jsonify(error=str(error)),400

    @app.errorhandler(HTTPException)
    def http_error(error):return jsonify(error=error.description),error.code

    @app.get('/')
    def landing(): return send_from_directory(ROOT/'static','platform.html')

    @app.get('/start')
    def start():return send_from_directory(ROOT/'static','platform.html')

    @app.post('/api/platform/try')
    def try_tournament():
        now=time.time();key='try:'+hashlib.sha256(peer_address().encode()).hexdigest()
        with registry() as db:
            db.execute('DELETE FROM limits WHERE expires<?',(now,))
            row=db.execute('SELECT * FROM limits WHERE address=?',(key,)).fetchone()
            if row and row['count']>=10:return jsonify(error='Bitte in 15 Minuten erneut versuchen.'),429
            db.execute('INSERT INTO limits VALUES(?,1,?) ON CONFLICT(address) DO UPDATE SET count=count+1',(key,now+900))
        return jsonify(trial.calculate(request.get_json(silent=True),ROOT/'static'/'demo.trf'))

    @app.get('/api/health')
    def health():
        with registry() as db:db.execute('SELECT 1').fetchone()
        return jsonify(ok=True)

    @app.get('/legal/<name>')
    def legal(name):
        if name not in ('terms','privacy','imprint') or not app.config['LEGAL_DIR']:return '',404
        return send_from_directory(app.config['LEGAL_DIR'],name+'.html')

    @app.get('/api/platform/status')
    def status():
        row=current_club(request.args.get('slug',''))
        return jsonify(ready=bool(row and row['status']=='active'),url=club_url(row['slug']) if row and row['status']=='active' else None)

    def prices():
        result=[]
        for plan in ('month','year'):
            price=billing.request(app.config,'prices/'+app.config['STRIPE_PRICE_'+plan.upper()])
            if not price.get('active') or price.get('currency')!='eur' or not isinstance(price.get('unit_amount'),int) or price['unit_amount']<=0 or price.get('recurring',{}).get('interval')!=plan or price.get('recurring',{}).get('interval_count')!=1:
                raise ValueError('Abo-Preise sind nicht vollständig eingerichtet.')
            result.append(dict(plan=plan,amount=price['unit_amount'],currency=price['currency']))
        return result

    @app.get('/static/<path:filename>')
    def static(filename):
        if filename not in ('platform.js','platform.css','style.css','icon.svg','demo.trf'): return '',404
        return send_from_directory(ROOT/'static',filename)

    @app.get('/api/platform/config')
    def settings():
        if not ready():return jsonify(checkout_ready=False,prices=[],tenant_domain=tenant_domain)
        try:return jsonify(checkout_ready=True,prices=prices(),tenant_domain=tenant_domain)
        except Exception:return jsonify(checkout_ready=False,prices=[],tenant_domain=tenant_domain)

    @app.post('/api/platform/checkout')
    def checkout():
        if not ready(): return jsonify(error='Online-Abos sind noch nicht eingerichtet.'),503
        try: prices()
        except Exception:return jsonify(error='Abo-Preise sind momentan nicht verfügbar.'),503
        data=request.get_json() or {}
        if not isinstance(data,dict):raise ValueError('Ungültige Anfrage')
        name=data.get('name','');slug=data.get('slug','');email=data.get('email','');username=data.get('username','');password=data.get('password','');plan=data.get('plan')
        if not isinstance(name,str) or not 2<=len(name.strip())<=100: raise ValueError('Vereinsname erforderlich')
        if not isinstance(slug,str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{2,39}',slug): raise ValueError('Vereinskürzel: 3–40 kleine Buchstaben, Ziffern und Bindestriche')
        if not isinstance(email,str) or not re.fullmatch(r'[^\s@]{1,64}@[^\s@]{1,180}\.[A-Za-z]{2,}',email): raise ValueError('Gültige E-Mail-Adresse erforderlich')
        if not isinstance(username,str) or not re.fullmatch(r'[A-Za-z0-9_.-]{3,50}',username) or not isinstance(password,str) or not 12<=len(password)<=200: raise ValueError('Benutzername und Passwort mit mindestens 12 Zeichen erforderlich')
        if plan not in ('month','year') or data.get('terms') is not True: raise ValueError('Abrechnungszeitraum und Bedingungen bestätigen')
        with registry() as db:
            now=time.time(); peer=peer_address()
            db.execute('DELETE FROM limits WHERE expires<?',(now,))
            row=db.execute('SELECT * FROM limits WHERE address=?',(peer,)).fetchone()
            if row and row['expires']>now and row['count']>=5: return jsonify(error='Bitte später erneut versuchen.'),429
            db.execute('INSERT INTO limits VALUES(?,1,?) ON CONFLICT(address) DO UPDATE SET count=CASE WHEN expires>? THEN count+1 ELSE 1 END,expires=CASE WHEN expires>? THEN expires ELSE excluded.expires END',(peer,now+3600,now,now))
        with registry() as db:
            existing=db.execute('SELECT * FROM clubs WHERE slug=?',(slug,)).fetchone()
            if existing:
                if existing['status']!='pending' or existing['plan']!=plan or existing['email']!=email or existing['username']!=username or existing['name']!=name.strip() or not password_work(check_password_hash,existing['password'],password):
                    raise ValueError('Vereinskürzel bereits reserviert')
                cid=existing['id']
            else:
                cid=secrets.token_hex(16)
                db.execute('INSERT INTO clubs(id,slug,name,email,username,password,plan,created) VALUES(?,?,?,?,?,?,?,?)',(cid,slug,name.strip(),email,username,password_work(generate_password_hash,password),plan,now))
        fields={'mode':'subscription','line_items[0][price]':app.config['STRIPE_PRICE_'+plan.upper()],
            'line_items[0][quantity]':'1','customer_email':email,'client_reference_id':cid,
            'metadata[club_id]':cid,'subscription_data[metadata][club_id]':cid,
            'success_url':app.config['PUBLIC_ORIGIN']+'/start?club='+slug,'cancel_url':app.config['PUBLIC_ORIGIN']+'/start?cancelled=1'}
        try: session=billing.request(app.config,'checkout/sessions',fields,'club-'+cid)
        except Exception:
            # A timeout can happen after Stripe created the session. Keep the
            # reservation; identical credentials retry the same idempotency key.
            return jsonify(error='Zahlungsdienst nicht erreichbar. Bitte erneut versuchen.'),502
        if not isinstance(session.get('url'),str) or urlparse(session['url']).hostname!='checkout.stripe.com' or urlparse(session['url']).scheme!='https': raise ValueError('Ungültige Zahlungsadresse')
        with registry() as db: db.execute('UPDATE clubs SET checkout=? WHERE id=?',(session['id'],cid))
        return jsonify(url=session['url'])

    @app.post('/api/platform/webhook')
    def webhook():
        event=billing.verify(request.get_data(),request.headers.get('Stripe-Signature',''),app.config['STRIPE_WEBHOOK_SECRET'])
        # The current deployment has one application process. Serialize remote
        # reads and state writes so concurrent deliveries cannot apply stale reads.
        with billing_lock:return process_webhook(event)

    def process_webhook(event):
        if not isinstance(event.get('id'),str) or not isinstance(event.get('created'),int): raise ValueError('Ungültiges Zahlungsereignis')
        obj=event.get('data',{}).get('object',{});kind=event.get('type')
        with registry() as db:
            if db.execute('SELECT 1 FROM events WHERE id=?',(event['id'],)).fetchone(): return jsonify(ok=True)
        if kind in ('checkout.session.completed','checkout.session.async_payment_succeeded'):
            with registry() as db: club=db.execute('SELECT * FROM clubs WHERE id=?',(obj.get('client_reference_id'),)).fetchone()
            if club and not club['checkout']:return jsonify(error='Checkout wird noch gespeichert. Bitte erneut zustellen.'),409
            if club and club['checkout']!=obj.get('id'):raise ValueError('Checkout-Zuordnung stimmt nicht überein')
            if club and obj.get('payment_status')=='paid' and obj.get('subscription'):
                subscription=billing.request(app.config,'subscriptions/'+obj['subscription'])
                if subscription.get('metadata',{}).get('club_id')!=club['id']: raise ValueError('Abo-Zuordnung stimmt nicht überein')
                if subscription.get('customer')!=obj.get('customer'):raise ValueError('Kunden-Zuordnung stimmt nicht überein')
                with registry() as db:
                    db.execute('UPDATE clubs SET status=?,customer=?,subscription=?,event_created=MAX(event_created,?) WHERE id=?',('active' if subscription.get('status')=='active' else 'suspended',subscription['customer'],obj['subscription'],event['created'],club['id']))
        elif kind in ('customer.subscription.updated','customer.subscription.deleted'):
            # Retrieve current state instead of trusting delivery order of webhook snapshots.
            with registry() as db:
                associated=db.execute('SELECT 1 FROM clubs WHERE subscription=?',(obj.get('id'),)).fetchone()
            if associated:
                subscription=billing.request(app.config,'subscriptions/'+obj['id'])
                with registry() as db:
                    db.execute('UPDATE clubs SET status=?,event_created=MAX(event_created,?) WHERE subscription=?',('active' if subscription.get('status') in ('active','trialing') else 'suspended',event['created'],obj['id']))
        with registry() as db: db.execute('INSERT OR IGNORE INTO events VALUES(?,?)',(event['id'],event['created']))
        return jsonify(ok=True)

    @app.route('/v/<slug>/',defaults={'path':''},methods=['GET','POST','HEAD'])
    @app.route('/v/<slug>/<path:path>',methods=['GET','POST','HEAD'])
    def club(slug,path):
        if tenant_domain:
            if request.method!='GET' and request.method!='HEAD':return jsonify(error='Bitte unter der neuen Vereinsadresse anmelden.'),409
            from flask import redirect
            return redirect(club_url(slug)+path+('?' + request.query_string.decode('ascii') if request.query_string else ''),code=302)
        return serve_club(slug,path,'/v/'+slug,app.config['PUBLIC_ORIGIN'])

    def serve_club(slug,path,prefix,public_origin):
        row=current_club(slug)
        if not row or row['status'] not in ('active','suspended'):return 'Vereinsbereich noch nicht freigeschaltet.',404
        child=tenant(row)
        if path=='api/billing/portal' and request.method=='POST':
            token=hashlib.sha256(request.cookies.get('club_session','').encode()).hexdigest()
            with storage.open_db(child.config['DATABASE']) as db:
                session=db.execute("SELECT s.csrf,u.role,u.permissions FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=? AND s.expires>? AND u.active=1",(token,time.time())).fetchone()
            if not session or not permissions.effective(session['role'],session['permissions'])['billing'] or not secrets.compare_digest(session['csrf'],request.headers.get('X-CSRF-Token','')):return jsonify(error='Administrator-Anmeldung erforderlich'),403
            if not row['customer']:return jsonify(error='Für diesen Verein ist noch kein bezahltes Abo hinterlegt.'),400
            result=billing.request(app.config,'billing_portal/sessions',dict(customer=row['customer'],return_url=public_origin+prefix+'/'))
            if urlparse(result.get('url','')).hostname!='billing.stripe.com' or urlparse(result.get('url','')).scheme!='https':raise ValueError('Ungültige Zahlungsadresse')
            return jsonify(url=result['url'])
        if row['status']=='suspended' and request.method=='POST' and path not in ('api/login','api/logout','api/password'):
            return jsonify(error='Abo pausiert. Daten bleiben lesbar und exportierbar; bitte das Abo verwalten.'),402
        env=request.environ.copy();env['SCRIPT_NAME']=prefix;env['PATH_INFO']='/'+path
        response=Response.from_app(child.wsgi_app,env)
        if response.mimetype=='text/html':
            body=response.get_data(as_text=True).replace('SK1912 Ludwigshafen',html.escape(row['name'],quote=True)).replace('SK1912 Wertung',html.escape(row['name'][:20],quote=True))
            body=body.replace('<head>','<head><meta name="club-platform" content="true">',1)
            body=re.sub(r'((?:href|src|action)=")(/(?!/))',lambda m:m[1]+prefix+m[2],body)
            response.set_data(body)
        if path=='static/manifest.webmanifest':
            manifest=json.loads(response.get_data())
            manifest.update(id=prefix+'/',name=row['name']+' · Vereinswertung',short_name=row['name'][:20],start_url=prefix+'/',scope=prefix+'/')
            for icon in manifest.get('icons',[]): icon['src']=prefix+icon['src']
            response.set_data(json.dumps(manifest))
        locations=response.headers.get('Location')
        if locations and locations.startswith('/') and not locations.startswith(prefix+'/'):response.headers['Location']=prefix+locations
        cookies=response.headers.getlist('Set-Cookie')
        if cookies:
            del response.headers['Set-Cookie']
            for cookie in cookies:response.headers.add('Set-Cookie',cookie.replace('Path=/','Path='+prefix+'/'))
        return response

    app.extensions['tenant_app']=tenant

    def sync_billing():
        with registry() as db:rows=db.execute('SELECT * FROM clubs WHERE subscription IS NOT NULL').fetchall()
        if rows and not app.config['STRIPE_SECRET_KEY']:raise ValueError('Stripe-Schlüssel für den Abo-Abgleich erforderlich')
        for row in rows:
            with billing_lock:
                subscription=billing.request(app.config,'subscriptions/'+row['subscription'])
                if subscription.get('metadata',{}).get('club_id')!=row['id'] or subscription.get('customer')!=row['customer']:raise ValueError('Abo-Zuordnung stimmt nicht überein')
                with registry() as db:db.execute('UPDATE clubs SET status=? WHERE id=? AND subscription=?',('active' if subscription.get('status') in ('active','trialing') else 'suspended',row['id'],row['subscription']))
        return len(rows)

    app.extensions['sync_billing']=sync_billing
    return app


if __name__=='__main__':
    from waitress import serve
    app=create_platform()
    def backups():
        from platform_manage import backup_platform
        while True:
            try:
                folder=Path(app.config['DATA_ROOT'])/'backups'
                if not folder.exists() or not any(folder.glob(time.strftime('%Y%m%d',time.gmtime())+'-*/complete.json')):
                    backup_platform(app)
            except Exception:logging.exception('Platform backup failed')
            try:app.extensions['sync_billing']()
            except Exception:logging.exception('Subscription reconciliation failed')
            time.sleep(3600)
    threading.Thread(target=backups,daemon=True).start()
    serve(app,host=os.environ.get('HOST','127.0.0.1'),port=int(os.environ.get('PORT','8082')),threads=8)
