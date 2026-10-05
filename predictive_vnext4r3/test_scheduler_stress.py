"""Virtual-time stress tests for the R3 queued-successor session design."""
from __future__ import annotations
import sys,unittest
from pathlib import Path
from datetime import timedelta
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))

from predictive_vnext4r3.scheduler import START,SESSION_SLOTS
from predictive_vnext4r3.worker import CONFIG

def simulate_slots(cadence,deadline,delays):
    issued=[];missed=[]
    for i,d in enumerate(delays):
        anchor=START+i*cadence
        arrival=anchor+timedelta(minutes=d)
        (issued if arrival<anchor+deadline else missed).append(i)
    return issued,missed

class StressTests(unittest.TestCase):
    def test_500_15m_slots_with_successor_start_lag(self):
        delays=[0.8,1.2,2,3,5,8,11,13]*63
        delays=delays[:500]
        issued,missed=simulate_slots(CONFIG["early15m"]["cadence"],CONFIG["early15m"]["deadline"],delays)
        self.assertEqual(len(issued),500)
        self.assertEqual(missed,[])

    def test_extreme_restart_delay_is_visible_not_backfilled(self):
        delays=[2]*200
        delays[73]=16
        issued,missed=simulate_slots(CONFIG["early15m"]["cadence"],CONFIG["early15m"]["deadline"],delays)
        self.assertEqual(missed,[73])
        self.assertNotIn(73,issued)
        self.assertIn(74,issued)

    def test_hourly_44m_recovery_still_admissible(self):
        delays=[1,5,15,25,35,44]*50
        issued,missed=simulate_slots(CONFIG["hourly"]["cadence"],CONFIG["hourly"]["deadline"],delays)
        self.assertFalse(missed)
        self.assertEqual(len(issued),300)

    def test_hourly_50m_restart_delay_is_visible_miss(self):
        delays=[2,4,50,3]*20
        issued,missed=simulate_slots(CONFIG["hourly"]["cadence"],CONFIG["hourly"]["deadline"],delays)
        self.assertTrue(missed)
        self.assertTrue(all(i%4==2 for i in missed))

    def test_session_length_below_hosted_runner_limit(self):
        self.assertEqual(SESSION_SLOTS["early15m"]*CONFIG["early15m"]["cadence"],timedelta(hours=4))
        self.assertEqual(SESSION_SLOTS["hourly"]*CONFIG["hourly"]["cadence"],timedelta(hours=4))

if __name__=="__main__":
    unittest.main()
