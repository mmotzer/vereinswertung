"""Bounded public Lichess export; URLs never determine the request destination."""
import json
import re
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta, date
from zoneinfo import ZoneInfo
from urllib.parse import urlencode


def fetch_match(first, second, day):
    for name in (first, second):
        if not isinstance(name,str) or not re.fullmatch(r'[A-Za-z0-9_-]{2,30}',name):
            raise ValueError('Bitte zwei gültige Lichess-Namen eingeben')
    if first.lower() == second.lower():
        raise ValueError('Zwei verschiedene Spieler auswählen')
    try:
        start = datetime.combine(date.fromisoformat(day),datetime.min.time(),ZoneInfo('Europe/Berlin'))
    except (ValueError,TypeError):
        raise ValueError('Bitte einen gültigen Spieltag auswählen')
    params = urlencode({'vs':second,'since':int(start.timestamp()*1000),
        'until':int((start+timedelta(days=1)).timestamp()*1000)-1,'max':31,
        'perfType':'bullet,blitz,rapid','finished':'true','ongoing':'false','moves':'false','clocks':'false'})
    request = urllib.request.Request('https://lichess.org/api/games/user/'+first+'?'+params,
        headers={'Accept':'application/x-ndjson','User-Agent':'SK1912-Vereinswertung/1.7'})
    try:
        with urllib.request.urlopen(request,timeout=25) as response:
            raw = response.read(1024*1024+1)
        if len(raw)>1024*1024:
            raise ValueError('Lichess-Antwort zu groß')
        games=[json.loads(line) for line in raw.splitlines() if line.strip()]
    except urllib.error.HTTPError as error:
        if error.code==404:
            raise ValueError('Lichess-Benutzername nicht gefunden. Bitte beide Namen prüfen.')
        if error.code==429:
            raise ValueError('Lichess begrenzt gerade die Anfragen. Bitte etwas später erneut laden.')
        raise ValueError('Lichess konnte die Partien nicht liefern. Bitte später erneut laden.')
    except (urllib.error.URLError,TimeoutError,json.JSONDecodeError):
        raise ValueError('Lichess derzeit nicht erreichbar. Bitte später erneut versuchen.')
    if not games:
        raise ValueError('Keine gemeinsamen Bullet-, Blitz- oder Schnellschachpartien an diesem Tag gefunden')
    if len(games)>30:
        raise ValueError('Mehr als 30 Partien gefunden. Bitte stattdessen einzelne Links verwenden')
    expected={first.lower(),second.lower()}
    if any({p.get('user',{}).get('name','').lower() for p in g.get('players',{}).values()} != expected for g in games):
        raise ValueError('Spieler im Export stimmen nicht überein')
    return sorted([parse_game(g) for g in games],key=lambda p:(p['played'],p['external_id']))


def fetch_games(links):
    if not isinstance(links, str) or len(links) > 12000:
        raise ValueError('Bitte Lichess-Partielinks eingeben')
    ids = []
    for link in links.split():
        match = re.fullmatch(r'https://lichess\.org/([A-Za-z0-9]{8})(?:[A-Za-z0-9]{4})?(?:/(?:white|black))?(?:#[0-9]+)?', link)
        if not match:
            raise ValueError('Nur direkte https://lichess.org/Partielinks sind erlaubt')
        if match[1] not in ids:
            ids.append(match[1])
    if not 1 <= len(ids) <= 30:
        raise ValueError('Bitte 1 bis 30 verschiedene Partielinks eingeben')
    request = urllib.request.Request('https://lichess.org/api/games/export/_ids?moves=false&clocks=false',
        data=','.join(ids).encode(), headers={'Accept':'application/x-ndjson',
        'Content-Type':'text/plain', 'User-Agent':'SK1912-Vereinswertung/1.7'})
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            raw = response.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ValueError('Lichess-Antwort zu groß')
        games = [json.loads(line) for line in raw.splitlines() if line.strip()]
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        raise ValueError('Lichess derzeit nicht erreichbar oder Export ungültig. Bitte später erneut versuchen.')
    if {g.get('id') for g in games} != set(ids) or len(games) != len(ids):
        raise ValueError('Mindestens eine Partie wurde nicht gefunden')
    return sorted([parse_game(g) for g in games], key=lambda p:(p['played'],p['external_id']))


def parse_game(g):
    if g.get('variant') != 'standard' or g.get('speed') not in ('bullet','blitz','rapid'):
        raise ValueError('Nur Standard-Schach in Bullet, Blitz oder Schnellschach wird gewertet')
    if g.get('status') not in ('mate','resign','stalemate','timeout','draw','outoftime'):
        raise ValueError('Nur regulär abgeschlossene Partien werden gewertet')
    players = []
    for number, color in enumerate(('white','black'),1):
        user = g.get('players',{}).get(color,{}).get('user',{})
        name = user.get('name','')
        if user.get('title') == 'BOT' or not re.fullmatch(r'[A-Za-z0-9_-]{2,30}',name):
            raise ValueError('Beide Spieler müssen menschliche Lichess-Konten haben')
        players.append({'number':number,'name':'Lichess: '+name})
    winner = g.get('winner')
    if winner not in (None,'white','black') or (winner is None and g['status'] not in ('draw','stalemate','outoftime')):
        raise ValueError('Partieergebnis ungültig')
    played = g.get('lastMoveAt',0)/1000
    if not 0 < played <= time.time() + 60:
        raise ValueError('Partiezeit ungültig')
    day = datetime.fromtimestamp(played,ZoneInfo('Europe/Berlin')).date().isoformat()
    gid = g['id']
    return {'external_id':gid,'played':played,'text':'lichess:'+gid,'filename':gid+'.lichess',
        'name':'Lichess · '+gid,'category':g['speed'],'round_dates':[day],
        'parsed':{'players':players,'rounds':1,'skipped':[],
        'games':[{'round':1,'white':1,'black':2,'score':1 if winner=='white' else 0 if winner=='black' else .5}]}}
