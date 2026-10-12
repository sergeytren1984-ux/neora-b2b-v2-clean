"""Causal regression for the single fixed daily BTC OTC forecast math.

Synthetic future perturbation must not alter prior-day forecasts, weights,
validation selection, risk guard, or prior matured outcomes. Unit math only.
"""
import datetime as dt,random,math,unittest
from btc_skill_rebuild.research_otc_rolling_risk_v7r6 import calculate
from btc_skill_rebuild.research_execution_drift_v7r6 import STEP
from btc_skill_rebuild.research_walkforward_barriers_v7r6 import UTC

class HistoricalRollingForwardMath(unittest.TestCase):
    def test_last_days_can_not_rewrite_prior_publication(self):
        first=dt.datetime(2026,8,7,18,55,tzinfo=UTC)
        rng=random.Random(48931)
        rows=[];p=83000.
        for i in range(18720):
            t=int((first+dt.timedelta(minutes=5*i)).timestamp()*1000)
            old=p;p*=math.exp(rng.gauss(0,.001))
            v=50+i%7;bu=v*(.49+.18*math.sin(i/21))
            rows.append([t,str(old),str(max(old,p)*1.0001),
                         str(min(old,p)*.9999),str(p),str(v),t+STEP-1,
                         '1',str(90+i%19),str(bu),'0','0'])
        original=calculate(rows)
        self.assertEqual(original['all_due_days'],28)
        self.assertTrue(original['complete_daily_due_grid'])
        self.assertEqual(original['first20_training_calibration_days'],20)
        self.assertEqual(original['next8_evaluated_outcomes'],8)
        # A future-only correction on Oct 10 evening cannot change ANY
        # signal or label fully matured by Oct 10 17:00 UTC.
        after=int(dt.datetime(2026,10,10,18,tzinfo=UTC).timestamp()*1000)
        for r in rows:
            if r[0]>=after:
                for k in (1,2,3,4):r[k]=str(float(r[k])*1.05)
        tampered=calculate(rows)
        self.assertEqual(original['rows'][:27],tampered['rows'][:27])
        self.assertFalse(tampered['trading_authority'])
        self.assertFalse(tampered['prospective_forecast_skill_proven'])
        self.assertEqual(tampered['actual_quoted_and_filled_OTC_orders'],0)

if __name__=='__main__':unittest.main()
