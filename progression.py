"""Personal activity progression, derived from active games; never affects ratings."""
from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo

ZONE = ZoneInfo('Europe/Berlin')
VERSION = '1'
LEVEL_EP = 1000


def calculate(rows, player_id):
    days, weeks, encounters, opponents, events, categories = set(), set(), set(), set(), set(), set()
    day_games = defaultdict(int)
    breakdown = dict(games=0, events=0, weeks=0, encounters=0)
    ledger = defaultdict(lambda: dict(games=0, events=0, weeks=0, encounters=0, count=0))
    monthly_encounters = defaultdict(int)
    for row in sorted(rows, key=lambda r: (r['played'], r['id'])):
        stamp = datetime.fromtimestamp(row['played'], ZONE)
        day, month = stamp.date().isoformat(), stamp.strftime('%Y-%m')
        week = stamp.isocalendar()[:2]
        opponent = row['black'] if row['white'] == player_id else row['white']
        days.add(day)
        opponents.add(opponent)
        categories.add(row['category'])
        day_games[day] += 1
        award = 50 if day_games[day] <= 5 else 10 if day_games[day] <= 15 else 0
        ledger[day]['games'] += award
        ledger[day]['count'] += 1
        if week not in weeks:
            ledger[day]['weeks'] += 100
            weeks.add(week)
        # One attendance bonus per calendar day, even across multiple TRF imports.
        if row['source'] == 'trf' and day not in events:
            ledger[day]['events'] += 150
            events.add(day)
        encounter = (month, opponent)
        if encounter not in encounters:
            if monthly_encounters[month] < 10:
                ledger[day]['encounters'] += 50
                monthly_encounters[month] += 1
            encounters.add(encounter)
    for item in ledger.values():
        for key in breakdown:
            breakdown[key] += item[key]
    total = sum(breakdown.values())
    level = total // LEVEL_EP + 1
    tracks = [
        ('Spielpraxis', sum(day_games.values()), [1, 10, 25, 50, 100, 250, 500, 1000]),
        ('Dabei sein', len(days), [1, 5, 10, 25, 50, 100, 250]),
        ('Begegnungen', len(opponents), [1, 5, 10, 20, 40, 60]),
        ('Am Vereinsbrett', len(events), [1, 5, 10, 25, 50, 100]),
        ('Beide Disziplinen', len(categories), [2]),
    ]
    badges = []
    for name, value, thresholds in tracks:
        achieved = [n for n in thresholds if value >= n]
        badges.append(dict(name=name, value=value, achieved=achieved,
                           next=next((n for n in thresholds if n > value), None)))
    return dict(version=VERSION, ep=total, level=level, progress=total % LEVEL_EP,
                next_level_ep=LEVEL_EP, remaining=LEVEL_EP-total % LEVEL_EP,
                stage=(level-1)//10+1, stage_level=(level-1)%10+1,
                breakdown=breakdown, badges=badges,
                recent=[dict(date=d, **ledger[d], ep=sum(ledger[d][k] for k in breakdown))
                        for d in sorted(ledger, reverse=True)[:12]])


def personal(db, user_id):
    member = db.execute('SELECT m.player_id,p.name FROM club_members m JOIN players p ON p.id=m.player_id WHERE m.user_id=?', (user_id,)).fetchone()
    if not member:
        return None
    rows = db.execute('''SELECT g.id,g.played,g.white,g.black,t.source,t.category
        FROM games g JOIN tournaments t ON t.id=g.tournament_id
        WHERE t.active=1 AND (g.white=? OR g.black=?)''', (member['player_id'], member['player_id'])).fetchall()
    return dict(player=dict(member), **calculate(rows, member['player_id']))


def community(db, now=None):
    now = now or datetime.now(ZONE)
    if now.tzinfo is None:
        raise ValueError('Timezone required')
    month = now.astimezone(ZONE).strftime('%Y-%m')
    count = 0
    for row in db.execute('''SELECT g.played FROM games g JOIN tournaments t ON t.id=g.tournament_id
        WHERE t.active=1 AND (EXISTS(SELECT 1 FROM club_members m WHERE m.player_id=g.white)
        OR EXISTS(SELECT 1 FROM club_members m WHERE m.player_id=g.black))'''):
        if datetime.fromtimestamp(row['played'], ZONE).strftime('%Y-%m') == month:
            count += 1
    # A shared milestone, not a deadline or obligation.
    return dict(month=month, games=count, milestone=(count//100+1)*100)
