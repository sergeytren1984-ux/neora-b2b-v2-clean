"""Numerical regression invariants for causal execution-horizon experiments."""
import unittest,math
from btc_skill_rebuild.research_execution_drift_v7r6 import (
    fit_ridge,predict,solve,SHRINK,HEADS)
class PriceMath(unittest.TestCase):
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
