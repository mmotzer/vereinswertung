"""Bounded Chess.com public archive and exported-PGN imports."""
import json
import re
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

NAME = r'[A-Za-z0-9_-]{2,30}'
DRAWS = {'agreed','repetition','stalemate','insufficient','50move','timevsinsufficient'}
LOSSES = {'checkmated','timeout','resigned','lose','abandoned'}


def game_id(url):
    if not isinstance(url,str): raise ValueError('Chess.com-Partielink fehlt')
    match = re.fullmatch(r'https://(?:www\.)?chess\.com/(?:game/live|live/game|analysis/game/live)/(\d{1,20})(?:\?[^\s#]*)?(?:#[^\s]*)?/?',url)
    if not match: raise ValueError('Nur direkte Chess.com-Live-Partielinks sind erlaubt')
    return 'chesscom:live:'+match[1]


def parse_game(g):
    if not isinstance(g,dict) or g.get('rules')!='chess' or g.get('time_class') not in ('bullet','blitz','rapid'):
        raise ValueError('Nur Standard-Schach in Bullet, Blitz oder Schnellschach wird gewertet')
    stamp=g.get('end_time')
    if isinstance(stamp,bool) or not isinstance(stamp,(int,float)) or not 0<stamp<=time.time()+60:
        raise ValueError('Chess.com-Partiezeit ungültig')
    players=[]; results=[]
    for number,color in enumerate(('white','black'),1):
        player=g.get(color,{})
        if not isinstance(player,dict): raise ValueError('Ungültige Chess.com-Spielerdaten')
        name=player.get('username','')
        if not isinstance(name,str) or not re.fullmatch(NAME,name) or player.get('title')=='BOT':
            raise ValueError('Zwei gültige menschliche Chess.com-Konten erforderlich')
        players.append(dict(number=number,name='Chess.com: '+name))
        results.append(player.get('result'))
    if players[0]['name'].casefold()==players[1]['name'].casefold(): raise ValueError('Zwei verschiedene Spieler erforderlich')
    if results[0]=='win' and results[1] in LOSSES: score=1
    elif results[1]=='win' and results[0] in LOSSES: score=0
    elif all(r in DRAWS for r in results): score=.5
    else: raise ValueError('Partie nicht regulär abgeschlossen oder Ergebnis widersprüchlich')
    gid=game_id(g.get('url'))
    day=datetime.fromtimestamp(stamp,ZoneInfo('Europe/Berlin')).date().isoformat()
    return dict(source='chesscom',external_id=gid,played=stamp,text=gid,filename=gid.replace(':','-')+'.chesscom',
        name='Chess.com-Vereinspartie',category=g['time_class'],round_dates=[day],
        parsed=dict(players=players,rounds=1,skipped=[],games=[dict(round=1,white=1,black=2,score=score)]))


def archive(username, year, month):
    url=f'https://api.chess.com/pub/player/{username.lower()}/games/{year:04d}/{month:02d}'
    request=urllib.request.Request(url,headers={'Accept':'application/json','User-Agent':'SK1912-Vereinswertung/1.22'})
    try:
        with urllib.request.urlopen(request,timeout=20) as response: raw=response.read(16*1024*1024+1)
        if len(raw)>16*1024*1024: raise ValueError('Chess.com-Monatsarchiv zu groß; bitte PGN verwenden')
        data=json.loads(raw)
        if not isinstance(data,dict) or not isinstance(data.get('games'),list): raise ValueError('Ungültiges Chess.com-Archiv')
        return data['games']
    except urllib.error.HTTPError as error:
        if error.code==404: return []
        if error.code==429: raise ValueError('Chess.com begrenzt gerade die Anfragen. Bitte später erneut laden.')
        raise ValueError('Chess.com konnte das Archiv nicht liefern. Bitte später erneut laden.')
    except (urllib.error.URLError,TimeoutError,json.JSONDecodeError):
        raise ValueError('Chess.com derzeit nicht erreichbar oder Export ungültig')


def fetch_match(first,second,day,link=''):
    if any(not isinstance(n,str) or not re.fullmatch(NAME,n) for n in (first,second)) or first.casefold()==second.casefold():
        raise ValueError('Zwei verschiedene gültige Chess.com-Namen eingeben')
    try: start=datetime.combine(date.fromisoformat(day),datetime.min.time(),ZoneInfo('Europe/Berlin'))
    except (ValueError,TypeError): raise ValueError('Gültigen Spieltag auswählen')
    end=start+timedelta(days=1)
    months={(t.year,t.month) for t in (start.astimezone(timezone.utc),(end-timedelta(seconds=1)).astimezone(timezone.utc))}
    target=game_id(link) if link else None
    expected={first.casefold(),second.casefold()}; items={}
    for year,month in sorted(months):
        for g in archive(first,year,month):
            if not isinstance(g,dict): continue
            if any(not isinstance(g.get(c),dict) or not isinstance(g[c].get('username'),str) for c in ('white','black')): continue
            names={g[c]['username'].casefold() for c in ('white','black')}
            stamp=g.get('end_time',0)
            if not isinstance(stamp,(int,float)) or not start.timestamp()<=stamp<end.timestamp() or names!=expected: continue
            if g.get('rules')!='chess' or g.get('time_class') not in ('bullet','blitz','rapid'): continue
            item=parse_game(g)
            if target and item['external_id']!=target: continue
            items[item['external_id']]=item
    if not items: raise ValueError('Keine passenden Chess.com-Partien im Archiv. Namen und Spieltag prüfen; neue Partien können erst später verfügbar sein.')
    if len(items)>30: raise ValueError('Mehr als 30 Partien gefunden. Bitte einen einzelnen Link verwenden.')
    return sorted(items.values(),key=lambda p:(p['played'],p['external_id']))


def parse_pgn(text):
    if not isinstance(text,str) or not 1<=len(text)<=1024*1024: raise ValueError('PGN-Datei darf höchstens 1 MB groß sein')
    # PGN headers are sufficient for result import; moves never affect the rating.
    chunks=re.split(r'(?=^\[Event\s)',text.strip(),flags=re.MULTILINE)
    items={}
    for chunk in chunks:
        if not chunk.strip(): continue
        tags={}
        for key,value in re.findall(r'^\[(\w+)\s+"([^"\r\n]*)"\]\s*$',chunk,flags=re.MULTILINE):
            if key in tags: raise ValueError('Doppelte PGN-Kopffelder')
            tags[key]=value
        try:
            stamp=datetime.strptime(tags['UTCDate']+' '+tags['EndTime'],'%Y.%m.%d %H:%M:%S').replace(tzinfo=timezone.utc).timestamp()
            # EndDate, when present, is authoritative for games crossing UTC midnight.
            if tags.get('EndDate'): stamp=datetime.strptime(tags['EndDate']+' '+tags['EndTime'],'%Y.%m.%d %H:%M:%S').replace(tzinfo=timezone.utc).timestamp()
            control=tags['TimeControl'].split('+'); base=int(control[0]); inc=int(control[1]) if len(control)==2 else 0
            if len(control)>2 or base<=0 or inc<0: raise ValueError()
            result=tags['Result']; pair={'1-0':('win','resigned'),'0-1':('resigned','win'),'1/2-1/2':('agreed','agreed')}[result]
            if tags.get('Variant','Standard') not in ('Standard','Chess'): raise ValueError()
            speed='bullet' if base+40*inc<180 else 'blitz' if base+40*inc<600 else 'rapid'
            item=parse_game(dict(url=tags.get('Link') or tags.get('Site'),rules='chess',time_class=speed,end_time=stamp,
                white=dict(username=tags['White'],result=pair[0]),black=dict(username=tags['Black'],result=pair[1])))
        except (KeyError,ValueError): raise ValueError('Chess.com-PGN benötigt Spieler, Ergebnis, Live-Partielink, TimeControl, UTCDate und EndTime; nur Standardpartien.')
        items[item['external_id']]=item
    if not 1<=len(items)<=30: raise ValueError('Bitte 1 bis 30 Chess.com-Partien importieren')
    return sorted(items.values(),key=lambda p:(p['played'],p['external_id']))
