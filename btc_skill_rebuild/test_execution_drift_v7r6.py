"""Numerical regression invariants for causal execution-horizon experiments."""
import unittest,math
from btc_skill_rebuild.research_execution_drift_v7r6 import (
    fit_ridge,predict,solve,SHRINK,HEADS,examples,STEP)
class PriceMath(unittest.TestCase):
    def test_one_hour_matures_inside_last_day_not_dropped_as_24h(self):
        n=12010
        rows=[]
        for i in range(n):
            at=i*STEP
            rows.append([at,'83000','83001','82999','83000','10',at+STEP-1,'0','50','5','0','0'])
        result=examples(rows)
        # Former one-size-fits-all 24h feature cutoff silently excluded 287
        # usable 1h/4h input anchors, biasing test coverage.
        self.assertEqual(result[-1][0],n-2)
        self.assertTrue(any(i==n-13 for i,*_ in result))
        self.assertTrue(any(i==n-49 for i,*_ in result))
        self.assertFalse(any(i==n for i,*_ in result))

    def test_normal_equation_recovery_and_regularization(self):
        a=[[3.,1.],[1.,2.]];b=[7.,5.]
        solution=solve(a,b)
        self.assertAlmostEqual(solution[0],1.8,places=10)
        self.assertAlmostEqual(solution[1],1.6,places=10)
        train=[]
        for i in range(1100):
            x=((i%23-11)/10.,(i%29-14)/9.)
            y=.002+.01*x[0]-.005*x[1]
            train.append((i,x,y))
        model=fit_ridge(train)
        self.assertAlmostEqual(predict(model,(0.,0.)),.002,delta=.0003)
        self.assertAlmostEqual(predict(model,(.5,-.4)),.009,delta=.0010)
        self.assertIn(0.,SHRINK)
        self.assertEqual(HEADS['OTC_wait_increment_t60_to_t120'],(12,24))

if __name__=='__main__':unittest.main()
