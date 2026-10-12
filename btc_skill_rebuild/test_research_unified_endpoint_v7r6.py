"""3-way endpoint of one v7R6 mathematical head, not same as barrier."""
import unittest,math
from btc_skill_rebuild.research_unified_endpoint_v7r6 import (
    endpoint_class,daily_scores,HORIZONS)
from btc_skill_rebuild.research_endpoint_24h_v7r6 import fit,predict

class OneMathAllHorizons(unittest.TestCase):
    def test_all_horizons_exact_three_exclusive_endpoint_outcomes(self):
        self.assertEqual(set(HORIZONS),{'1h','4h','24h'})
        for name,(steps,threshold) in HORIZONS.items():
            self.assertEqual(endpoint_class(83000.,83000.,threshold),2)
            self.assertEqual(endpoint_class(83000.,83000*(1+threshold),threshold),0)
            self.assertEqual(endpoint_class(83000.,83000*(1-threshold),threshold),1)
            self.assertEqual(endpoint_class(83000.,83000*(1+threshold*.5),threshold),2)
            for bad in (0,-100,float('nan')):
                with self.assertRaises(ValueError):endpoint_class(83000.,bad,threshold)

    def test_identical_math_predicts_probability_simplex(self):
        example=[]
        for i in range(1600):
            x=[math.sin(i/(4+j)) for j in range(17)]
            example.append((i*900000,tuple(x),i%3))
        model=fit(example)
        for alpha in (0.,.25,.5,1.):
            for i in (0,30,100):
                p=predict(model,example[i][1],alpha)
                self.assertAlmostEqual(sum(p),1.,places=10)
                self.assertEqual(len(p),3)
                self.assertTrue(all(0<=v<=1 for v in p))
            score=daily_scores(example[1450:1590],model,alpha)
            self.assertEqual(score['n'],140)
            self.assertEqual(sum(score['up_down_range']),140)

if __name__=='__main__':unittest.main()