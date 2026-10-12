"""Mathematical invariants, not historical forecast accuracy tests."""
import unittest
from btc_skill_rebuild.research_otc_timing_robustness_v7r6 import (
    bounded_btc_difference,classify,interval_prices)

class FutureOTCTimingRisk(unittest.TestCase):
    def test_markup_uncertainty_changes_action(self):
        low,up=bounded_btc_difference(83000,83000,82700,82700)
        self.assertEqual(classify(low,up),'WAIT_ROBUST')
        lo,hi=bounded_btc_difference(83000,83000,82960,82960)
        self.assertEqual(classify(lo,hi),'NOT_IDENTIFIABLE')
        lo,hi=bounded_btc_difference(83000,83000,83300,83300)
        self.assertEqual(classify(lo,hi),'NOW_ROBUST')
        with self.assertRaises(ValueError):bounded_btc_difference(83001,83000,82000,82001)
        with self.assertRaises(ValueError):bounded_btc_difference(83000,83000,-1,82000)

    def test_timing_uncertainty_cannot_create_more_robust_results(self):
        # Under inclusion of future prices, lower bound may only decrease;
        # upper bound may only increase. A decisive sign cannot emerge
        # merely from a WIDER execution-time uncertainty set.
        rows=[]
        base=83000.
        for i in range(100):
            p=base+(i-30)*17+(350 if i%4==0 else -110 if i%7==0 else 0)
            rows.append([i*300000,str(p),str(p+25),str(p-25),str(p),'1',i*300000+299999])
        for mode in ('closed_5m','intrabar_5m'):
            previous=None
            for window in (0,5,10,15,30):
                nmin,nmax=interval_prices(rows,0,60,window,mode)
                wmin,wmax=interval_prices(rows,0,120,window,mode)
                lo,hi=bounded_btc_difference(nmin,nmax,wmin,wmax)
                if previous is not None:
                    self.assertLessEqual(lo,previous[0]+1e-12)
                    self.assertGreaterEqual(hi,previous[1]-1e-12)
                previous=(lo,hi)
        with self.assertRaises(ValueError):interval_prices(rows,0,60,7,'closed_5m')
        with self.assertRaises(ValueError):interval_prices(rows,0,120,125,'closed_5m')

if __name__=='__main__':unittest.main()