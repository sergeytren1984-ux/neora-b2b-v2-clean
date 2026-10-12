"""Invariant checks for the existing v7R6 24h three-way endpoint mathematics."""
from __future__ import annotations
import datetime as dt,math,unittest
from btc_skill_rebuild.research_endpoint_24h_v7r6 import target,fit,predict,evaluate,STEPS,STEP,LIMIT

class End24hMath(unittest.TestCase):
    def test_three_mutually_exclusive_endpoint_outcomes(self):
        self.assertEqual(STEPS*STEP//60000,1440)
        self.assertEqual(target(83000.,83000.*1.019),2)
        self.assertEqual(target(83000.,83000.*1.021),0)
        self.assertEqual(target(83000.,83000.*0.979),1)
        self.assertEqual(target(83000.,83000.*0.99),2)
        for v in (0.,float('nan'),-100):
            with self.assertRaises(ValueError):target(83000.,v)

    def test_probabilities_and_conditional_direction_ablation(self):
        base=int(dt.datetime(2026,8,9,tzinfo=dt.timezone.utc).timestamp()*1000)
        train=[]
        for i in range(1900):
            x=(math.sin(i/31),math.cos(i/19),i%13/20)
            y=(0 if i%11==0 else 1 if i%13==0 else 2)
            train.append((base+i*STEP,x,y))
        model=fit(train)
        for x in ((0.,0.,0.),(-1.,1.,.3),(.2,-.1,.4)):
            p=predict(model,x,1.)
            self.assertEqual(len(p),3)
            self.assertAlmostEqual(sum(p),1.,places=10)
            self.assertTrue(all(0<=v<=1 for v in p))
        selected=evaluate(train[-300:],model,.5)
        self.assertEqual(selected['n_overlap_15m'],300)
        self.assertIn('direction_increment_brier_vs_same_event_probability',selected)
        self.assertEqual(model[3][0]+model[3][1]+model[3][2],1.)
        self.assertFalse(any(math.isnan(z) for z in model[3]))

if __name__=='__main__':unittest.main()
