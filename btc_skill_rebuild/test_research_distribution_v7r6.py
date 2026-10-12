"""Forecast numerical skill—not GitHub reliability. Regression/causality checks."""
import copy,datetime as dt,math,random,unittest
from btc_skill_rebuild.research_distribution_v7r6 import (
    walk_to_barrier_probability,scan,STEP,TRAIN_CUTOFF,VALIDATION_CUTOFF)

class ForecastMath(unittest.TestCase):
    def test_first_passage_probability_no_drift(self):
        b=math.log1p(.007)
        p=[walk_to_barrier_probability(t,b) for t in
           (0.,.00000001,.000001,.00001,.0001,.001)]
        self.assertEqual(p[0],0.)
        self.assertTrue(all(0<=x<=1 for x in p),p)
        self.assertTrue(all(x<=y for x,y in zip(p,p[1:])),p)
        with self.assertRaises(ValueError):walk_to_barrier_probability(float('nan'),b)
        with self.assertRaises(ValueError):walk_to_barrier_probability(-1.,b)
        with self.assertRaises(ValueError):walk_to_barrier_probability(.01,0.)

    @staticmethod
    def synthetic():
        rng=random.Random(19631)
        start=dt.datetime(2026,8,7,18,55,tzinfo=dt.timezone.utc)
        price=83000.
        rows=[]
        for i in range(18720):
            at=int((start+dt.timedelta(minutes=5*i)).timestamp()*1000)
            op=price;price*=math.exp(rng.gauss(0,.0016))
            hi=max(op,price)*1.00008;lo=min(op,price)*.99992
            rows.append([at,f'{op:.8f}',f'{hi:.8f}',f'{lo:.8f}',f'{price:.8f}',
                         '3',at+STEP-1,'0','10','1','0','0'])
        return rows

    def test_forward_label_embargo_historical_isolation(self):
        r=self.synthetic()
        first=scan(r)
        self.assertTrue(first['historical_period_already_known_to_developers'])
        self.assertFalse(first['trading_authority'])
        self.assertEqual(first['execution_aligned_spot_proxy']['price_future_buy_target_minutes_after_publication'],60)
        self.assertEqual(first['execution_aligned_spot_proxy']['price_future_wait_target_minutes_after_publication'],120)
        self.assertTrue(first['execution_aligned_spot_proxy']['no_actual_operator_fills_or_acceptance_observed'])
        self.assertEqual(set(first['horizons']),{'1h','4h','24h'})
        # Change ONLY observations dated AFTER the old test boundary.
        # Causal TRAIN and validation components must remain bit-for-bit
        # unchanged, including trend and volatility scaling decisions.
        j=int((VALIDATION_CUTOFF-dt.datetime(2026,8,7,18,55,tzinfo=dt.timezone.utc)).total_seconds()/300)
        for row in r[j:]:
            for k in (1,2,3,4):row[k]=f'{float(row[k])*1.02:.8f}'
        second=scan(r)
        for h in ('1h','4h','24h'):
            for key in ('train','validation','train_selected_vol_scale',
                        'train_selected_point_trend_shrink'):
                self.assertEqual(first['horizons'][h][key],second['horizons'][h][key])
        for key in ('train','validation','selected_by_training_day_ci_only'):
            self.assertEqual(first['execution_aligned_spot_proxy'][key],second['execution_aligned_spot_proxy'][key])
        # Signed claim is forbidden even if retrospective performance rises.
        self.assertFalse(second['directional_edge_proven'])
        self.assertFalse(second['price_edge_proven'])
        r[100][6]=r[100][6]+60000
        with self.assertRaises(ValueError):scan(r)

if __name__=='__main__':unittest.main()
