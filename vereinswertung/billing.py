"""Stripe Checkout/Portal and signed webhooks. Keys and prices come from the host."""
import hashlib
import hmac
import json
import time
import urllib.request
from urllib.parse import urlencode


def request(config, path, fields=None, idempotency=None):
    headers={'Authorization':'Bearer '+config['STRIPE_SECRET_KEY'],'Stripe-Version':'2025-03-31.basil'}
    if fields is not None: headers['Content-Type']='application/x-www-form-urlencoded'
    if idempotency: headers['Idempotency-Key']=idempotency
    req=urllib.request.Request('https://api.stripe.com/v1/'+path,
        data=urlencode(fields).encode() if fields is not None else None,headers=headers)
    with urllib.request.urlopen(req,timeout=20) as response:
        data=response.read(1024*1024+1)
    if len(data)>1024*1024: raise ValueError('Zahlungsantwort zu groß')
    return json.loads(data)


def verify(raw, signature, secret, now=None):
    if not secret or not isinstance(signature,str): raise ValueError('Webhook-Konfiguration fehlt')
    pairs=[part.split('=',1) for part in signature.split(',') if '=' in part]
    stamps=[value for key,value in pairs if key=='t']
    if len(stamps)!=1: raise ValueError('Ungültige Webhook-Signatur')
    try: stamp=int(stamps[0])
    except ValueError: raise ValueError('Ungültige Webhook-Signatur')
    if abs((time.time() if now is None else now)-stamp)>300: raise ValueError('Webhook-Signatur abgelaufen')
    expected=hmac.new(secret.encode(),str(stamp).encode()+b'.'+raw,hashlib.sha256).hexdigest()
    if not any(key=='v1' and hmac.compare_digest(value,expected) for key,value in pairs):
        raise ValueError('Ungültige Webhook-Signatur')
    event=json.loads(raw)
    if not isinstance(event,dict):raise ValueError('Ungültiges Zahlungsereignis')
    return event
