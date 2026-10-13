"""No look-ahead in the v7R6 three-horizon adaptive-reference mathematics.

Synthetic tests verify maturity-gating at the EXACT issue timestamp and
that the future cannot rewrite a frozen historical conditional baseline.
They are not proof of BTC directional forecasting accuracy.
"""
from __future__ import annotations
import math,unittest
from btc_skill_rebuild.research_adaptive_climatology_v7r6 import (
    CausalClimatology,endpoint_class,BASELINES,HORIZONS,DAY,
    nonoverlap_training_prior,independent_due_climatology_population,
    baseline_probability)

class ProperReferenceContract(unittest.TestCase):
    def test_three_mutually_exclusive_endpoint_outcomes(self):
        self.assertEqual(HORIZONS['1h'],(12,.007))
        self.assertEqual(HORIZONS['4h'],(48,.012))
        self.assertEqual(HORIZONS['24h'],(288,.02))
        self.assertEqual(endpoint_class(83000,83000*(1+.007),.007),0)
        self.assertEqual(endpoint_class(83000,83000*(1-.007),.007),1)
        self.assertEqual(endpoint_class(83000,83000,.007),2)
        for p in (0.,-100.,float('nan')):
            with self.assertRaises(ValueError):endpoint_class(83000,p,.02)

    def _population(self,lag=4*900000):
        origin=1_700_000_000_000
        sample=[]
        for i in range(31*24*4):
            at=origin+i*900000
            sample.append((at,at+lag,(0.,)*17,i%3))
        return sample

    def test_mutating_any_immature_future_labels_does_not_change_baseline(self):
        population=self._population()
        c=CausalClimatology(population)
        time=population[1200][0]
        for window in (7,14):
            expected=c.probability(time,window)
            changed=[(t,m,x,(2-y) if m>time else y) for t,m,x,y in population]
            after=CausalClimatology(changed).probability(time,window)
            self.assertEqual(expected,after)
            self.assertAlmostEqual(sum(expected),1.,places=12)

    def test_latest_fully_mature_label_is_only_used_after_maturity(self):
        population=self._population()
        c=CausalClimatology(population)
        i=1200
        due=population[i][1]
        earlier=c.probability(due-1,7)
        ontime=c.probability(due,7)
        self.assertEqual(earlier,ontime)
        self.assertNotEqual(ontime,c.probability(due+1,7))
        # Force a drastic later-only rewrite: should not affect past.
        changed=[(t,m,x,0 if m>=due else y) for t,m,x,y in population]
        edited=CausalClimatology(changed)
        self.assertEqual(earlier,edited.probability(due-1,7))

    def test_empty_matured_window_no_fabricated_precision(self):
        base=1_700_000_000_000
        rows=[(base+i*900000,base+i*900000+24*3600000,(0.,)*17,i%3) for i in range(100)]
        climatology=CausalClimatology(rows)
        self.assertEqual(climatology.probability(base,7),[1/3]*3)
        with self.assertRaises(ValueError):climatology.probability(base,30)
        self.assertEqual(BASELINES,(
            'frozen_training_prior','matured_rolling_7day','matured_rolling_14day'))

    def test_reject_duplicate_sources_and_invalid_outcome_class(self):
        rows=self._population()
        with self.assertRaises(ValueError):
            CausalClimatology(rows[:3]+[rows[2]])
        changed=rows[:3]+[(rows[3][0],rows[3][1],rows[3][2],3)]+rows[4:]
        with self.assertRaises(ValueError):CausalClimatology(changed)

    def test_frozen_train_prior_must_match_independent_due_grid(self):
        # A single daily movement must not be counted 12 times by a
        # 15m (here synthetic 5m) TRAIN prior while 7/14d baselines
        # use the nonoverlapping horizon grid.
        from btc_skill_rebuild.research_execution_drift_v7r6 import STEP
        train=[(i*STEP,(0.,),1 if i%12==0 else 0) for i in range(120)]
        corrected=nonoverlap_training_prior(train,12)
        overlapping=[(sum(y==k for _,_,y in train)+1)/(len(train)+3)
                     for k in range(3)]
        self.assertAlmostEqual(corrected[1],11/13)
        self.assertGreater(corrected[1],overlapping[1]+0.7)
        self.assertAlmostEqual(sum(corrected),1.)
        self.assertEqual(corrected,baseline_probability(
            'frozen_training_prior',120*STEP,corrected,None))
        # Horizon 24h uses only ONE due per UTC day, never 96
        # overlapping 15m targets from the same movement.
        long=[(i*STEP,(0.,),1 if i%288==0 else 0) for i in range(288*8)]
        day_prior=nonoverlap_training_prior(long,288)
        self.assertAlmostEqual(day_prior[1],9/11)
        self.assertGreater(day_prior[1],0.8)

    def test_train_grid_prior_excludes_mismatched_and_empty_slots(self):
        from btc_skill_rebuild.research_execution_drift_v7r6 import STEP
        with self.assertRaises(ValueError):
            nonoverlap_training_prior([(STEP,(0.,),1)],12)
        with self.assertRaises(ValueError):
            nonoverlap_training_prior([(0,(0.,),3)],12)
        with self.assertRaises(ValueError):
            nonoverlap_training_prior([(0,(0.,),0)],0)

    def test_rolling_prior_and_train_prior_same_fixed_grid(self):
        from btc_skill_rebuild.research_execution_drift_v7r6 import STEP
        horizon=12
        # Deterministic issue times; all labels mature after 1h.
        rows=[(i*STEP,(i+horizon+1)*STEP,(0.,),i%3)
              for i in range(30*24*12)]
        climate=CausalClimatology(independent_due_climatology_population(
            rows,horizon))
        at=rows[-1][0]
        for days in (7,14):
            selected=climate.probability(at,days)
            start=at-days*DAY
            matured=[y for t,d,_,y in rows
                     if t%(horizon*STEP)==0 and start<=t and d<at]
            counts=[sum(y==k for y in matured) for k in range(3)]
            expected=[(c+1)/(len(matured)+3) for c in counts]
            self.assertEqual(selected,expected)
            # A fabricated later-only class cannot affect earlier issue.
            modified=[(t,d,x,2 if d>=at else y) for t,d,x,y in rows]
            edited=CausalClimatology(independent_due_climatology_population(
                modified,horizon))
            self.assertEqual(selected,edited.probability(at,days))


if __name__=='__main__':
    unittest.main()
