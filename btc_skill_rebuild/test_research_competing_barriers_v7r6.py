"""Unit test the causal competing-barrier math (especially clock units)."""
import datetime as dt,math,unittest
from unittest.mock import patch
from btc_skill_rebuild.research_competing_barriers_v7r6 import labels,alert_score,classify_threshold,LABELS
from btc_skill_rebuild.research_distribution_v7r6 import STEP,UTC

class MathAdversarial(unittest.TestCase):
    def test_competing_first_touch_and_5m_ambiguity(self):
        now=int(dt.datetime(2026,9,5,tzinfo=UTC).timestamp()*1000)
        data=[[now+i*STEP,'83000','83030','82970','83000','1',now+(i+1)*STEP-1]
              for i in range(60)]
        base=83000
        data[4][2]='83800'   # up touch first
        data[9][3]='82000'   # down later: shouldn't win
        self.assertEqual(labels(data,0,12,.007),(0,4))
        data[4][3]='82000'
        self.assertEqual(labels(data,0,12,.007),(3,4))
        data[4][2]='83030';data[4][3]='82970'
        self.assertEqual(labels(data,0,12,.007),(1,9))
        data[9][3]='82970'
        self.assertEqual(labels(data,0,12,.007),(2,None))

    def test_constant_prior_never_generates_pseudo_alerts(self):
        t=int(dt.datetime(2026,9,29,tzinfo=UTC).timestamp()*1000)
        x=[0.]*17
        m=([0.]*17,[1.]*17,[[0.]*18 for _ in LABELS],[.25]*4)
        val=[(t+i*900000,x,2,None) for i in range(100)]
        threshold=classify_threshold(val,m,0.)
        self.assertIsNone(threshold)
        scored=alert_score(val,m,0.,threshold)
        self.assertEqual(scored['signals_under_one_per_day_cap'],0)
        self.assertEqual(scored['correct_first_barrier'],0)

    def test_one_hour_cannot_claim_sixty_minute_advance(self):
        # A test event at the last 5m candle of a 1h horizon:
        # its earliest touch is +55min, not +60min and not years later.
        t=int(dt.datetime(2026,9,29,tzinfo=UTC).timestamp()*1000)
        x=[0.]*17
        model=([0.]*17,[1.]*17,[[0.]*18 for _ in LABELS],[.25]*4)
        sample=[(t,x,0,t+60*60000)]
        with patch('btc_skill_rebuild.research_competing_barriers_v7r6.prob',return_value=[.9,.02,.07,.01]):
            result=alert_score(sample,model,1.,.5)
        self.assertEqual(result['correct_first_barrier'],1)
        self.assertEqual(result['correct_with_lead30m'],1)
        self.assertEqual(result['correct_with_lead60m'],0)
        # For the first 5m future candle, conservative lead is ZERO.
        sample=[(t,x,0,t+STEP)]
        with patch('btc_skill_rebuild.research_competing_barriers_v7r6.prob',return_value=[.9,.02,.07,.01]):
            result=alert_score(sample,model,1.,.5)
        self.assertEqual(result['correct_with_lead30m'],0)

if __name__=='__main__':unittest.main()