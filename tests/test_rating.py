import unittest
from dataclasses import replace
from vereinswertung.rating import Rating, compute_one, live, game, regulate, COLOR_ADVANTAGE, SCALE, PERIODS_PER_DAY


class LichessReferenceTests(unittest.TestCase):
    """Numbers copied from pinned scalachess tests, NOT derived from our port."""
    def test_color_advantage_reference_vectors(self):
        vectors = [
            # white/black parameters, outcome, expected white/black rating and RD
            ((1500,350,.06),(1500,350,.06),1,1658.56,1341.44,290.2538,290.2538),
            ((1500,350,.06),(1500,350,.06),0,1334.08,1665.92,290.2538,290.2538),
            ((1500,350,.06),(1500,350,.06),.5,1496.32,1503.68,290.2538,290.2538),
            ((1400,79,.06),(1550,110,.065),1,1422.16,1507.28,77.4603,105.7716),
            ((1400,79,.06),(1550,110,.065),0,1389.55,1569.75,77.4603,105.7716),
            ((1400,79,.06),(1550,110,.065),.5,1405.85,1538.51,77.4603,105.7716),
            ((1200,60,.053),(1850,200,.062),1,1216.68,1636.77,59.8952,196.7954),
            ((1200,60,.053),(1850,200,.062),0,1199.25,1855.77,59.8952,196.7954),
            ((1200,60,.053),(1850,200,.062),.5,1207.97,1746.27,59.8952,196.7954),
        ]
        for wp,bp,score,wr,br,wrd,brd in vectors:
            with self.subTest(wp=wp,score=score):
                w,b = Rating(*wp),Rating(*bp)
                nw = compute_one(w,b,score,COLOR_ADVANTAGE)
                nb = compute_one(b,w,1-score,-COLOR_ADVANTAGE)
                self.assertAlmostEqual(nw.rating,wr,delta=.005)
                self.assertAlmostEqual(nb.rating,br,delta=.005)
                self.assertAlmostEqual(nw.rd,wrd,delta=.00005)
                self.assertAlmostEqual(nb.rd,brd,delta=.00005)

    def test_volatility_reference(self):
        r=Rating(1500,350,.06)
        expected = {1:.0599992,0:.0599993,.5:.0599977}
        for score,vol in expected.items():
            self.assertAlmostEqual(compute_one(r,r,score,COLOR_ADVANTAGE).volatility,vol,delta=.0000001)
        w,b=Rating(1200,60,.053),Rating(1850,200,.062)
        self.assertAlmostEqual(compute_one(w,b,1,COLOR_ADVANTAGE).volatility,.053013,delta=.000001)
        self.assertAlmostEqual(compute_one(b,w,0,-COLOR_ADVANTAGE).volatility,.062028,delta=.000001)

    def test_default_reference_without_color(self):
        r=Rating()
        nw=compute_one(r,r,1)
        self.assertAlmostEqual(nw.rating,1741,delta=1)
        self.assertAlmostEqual(nw.rd,396,delta=1)
        self.assertAlmostEqual(nw.volatility,.0899983,delta=.00000001)

    def test_regulator_is_category_specific(self):
        before=Rating(1500,80,.06)
        after=replace(before,rating=1600)
        self.assertAlmostEqual(regulate(before,after,'blitz',1).rating,1600.5)
        self.assertAlmostEqual(regulate(before,after,'rapid',1).rating,1601.5)
        self.assertEqual(regulate(before,replace(after,rating=1400),'rapid',1).rating,1400)

    def test_inactivity_uses_days_only(self):
        r=Rating(1800,60,.06,20,1000)
        inflated=live(r,1000+365*86400)
        self.assertEqual(inflated.rating,1800)
        self.assertAlmostEqual(inflated.rd,110,delta=1)
        self.assertEqual(live(r,1000),r)
        self.assertEqual(live(r,1000+20000*86400).rd,500)
        self.assertEqual(live(Rating(),1000000).rd,500)

    def test_both_players_use_before_state(self):
        w,b=Rating(),Rating()
        nw,nb=game(w,b,1,'blitz',100)
        self.assertEqual(nw,regulate(w,compute_one(w,b,1,COLOR_ADVANTAGE),'blitz',100))
        self.assertEqual(nb,regulate(b,compute_one(b,w,0,-COLOR_ADVANTAGE),'blitz',100))
        self.assertEqual(w,Rating())

    def test_no_per_game_inflation(self):
        r=Rating(1500,60,.06,20,100)
        nw,_=game(r,r,.5,'blitz',100)
        self.assertLess(nw.rd,r.rd)
        self.assertEqual(nw.games,21)


if __name__=='__main__':
    unittest.main()
