import unittest
from datetime import datetime
from zoneinfo import ZoneInfo
from vereinswertung.progression import calculate


def games(count, day='2026-10-04', source='lichess', start=0, opponent=2, category='blitz'):
    stamp = datetime.fromisoformat(day+'T23:30:00+02:00').timestamp()
    return [dict(id=start+i, played=stamp+i, white=1, black=opponent, source=source, category=category) for i in range(count)]


class ProgressionTests(unittest.TestCase):
    def test_daily_cap_and_participation_once_across_categories(self):
        p = calculate(games(20)+games(1,source='trf',start=30)+games(1,source='trf',start=31,category='rapid'),1)
        self.assertEqual(p['breakdown'],dict(games=350,events=150,weeks=100,encounters=50))
        self.assertEqual(p['badges'][0]['value'],22)
        self.assertEqual(p['badges'][-1]['achieved'],[2])

    def test_weeks_opponents_and_months(self):
        rows=games(1)+games(1,day='2026-10-05',start=5)+games(1,day='2026-11-01',start=10)
        p=calculate(rows,1)
        self.assertEqual(p['breakdown']['encounters'],100)
        self.assertEqual(p['breakdown']['weeks'],300)
        many=[g for n in range(20) for g in games(1,start=n,opponent=n+2)]
        self.assertEqual(calculate(many,1)['breakdown']['encounters'],500)

    def test_level_boundaries_order_and_rollback(self):
        rows=[g for n in range(3) for g in games(5,day=f'2026-10-{n+1:02}',start=n*10,source='trf')]
        p=calculate(rows,1)
        self.assertEqual(p,calculate(list(reversed(rows)),1))
        self.assertEqual(p['level'],2)
        self.assertEqual(p['ep'],1350)
        self.assertEqual(calculate([],1)['level'],1)
        self.assertLess(calculate(rows[:-5],1)['ep'],p['ep'])

    def test_berlin_midnight(self):
        rows=games(1)
        rows[0]['played']=datetime(2026,10,4,22,30,tzinfo=ZoneInfo('UTC')).timestamp()
        self.assertEqual(calculate(rows,1)['recent'][0]['date'],'2026-10-05')
