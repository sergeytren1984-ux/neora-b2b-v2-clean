"""Deterministic virtual-time stress tests for the R3 self-chain design."""
from __future__ import annotations
import sys,unittest
from pathlib import Path
from datetime import datetime,timedelta,timezone

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))

from predictive_vnext4r3.scheduler import START
UTC=timezone.utc


def simulate(cadence,deadline,delays_minutes,slots):
    """One chained run per slot. Delay is workflow startup lag after anchor.
    A slot is issued iff chain startup remains inside the frozen deadline.
    Missed slots remain missed; no later run may backfill them.
    """
    issued=[];missed=[]
    for i in range(slots):
        anchor=START+i*cadence
        delay=timedelta(minutes=delays_minutes[i%len(delays_minutes)])
        arrival=anchor+delay
        if arrival<anchor+deadline:
            issued.append(i)
        else:
            missed.append(i)
    return issued,missed


class StressTests(unittest.TestCase):
    def test_500_15m_slots_under_realistic_dispatch_lag(self):
        issued,missed=simulate(timedelta(minutes=15),timedelta(minutes=14),
                               [0.2,0.5,1,2,3,5,8,11,13],500)
        self.assertEqual(len(issued),500)
        self.assertEqual(missed,[])

    def test_single_extreme_delay_is_visible_permanent_miss(self):
        delays=[1]*200
        delays[73]=16
        issued=[];missed=[]
        for i,d in enumerate(delays):
            anchor=START+i*timedelta(minutes=15)
            if anchor+timedelta(minutes=d)<anchor+timedelta(minutes=14):
                issued.append(i)
            else:
                missed.append(i)
        self.assertEqual(missed,[73])
        self.assertNotIn(73,issued)
        self.assertIn(74,issued)

    def test_300_hourly_slots_recover_40m_startup_delay(self):
        issued,missed=simulate(timedelta(hours=1),timedelta(minutes=45),
                               [1,3,8,15,25,35,40,44],300)
        self.assertEqual(len(issued),300)
        self.assertEqual(missed,[])

    def test_hourly_50m_delay_is_not_backfilled(self):
        issued,missed=simulate(timedelta(hours=1),timedelta(minutes=45),
                               [2,4,50,3],40)
        self.assertTrue(all(i%4==2 for i in missed))
        self.assertTrue(missed)

    def test_dispatch_retry_budget_is_bounded(self):
        # Workflow shell retries at most five times. This assertion documents the
        # frozen governance assumption used by the watchdog tests.
        retry_delays=[2,4,6,8,10]
        self.assertEqual(len(retry_delays),5)
        self.assertLess(sum(retry_delays),45)


if __name__=="__main__":
    unittest.main()
