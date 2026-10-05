"""Deterministic scheduler regression tests for vNext4R3."""
from __future__ import annotations
import sys,unittest
from pathlib import Path
from datetime import datetime,timedelta,timezone

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))

from predictive_vnext4r3.scheduler import (
    START,next_forecast_wake,next_outcome_wake,finalized_forecast
)
from predictive_vnext4r3.worker import CONFIG,slot_text

UTC=timezone.utc


def ev(key):
    return ({"idempotency_key":key},None)


class SchedulerTests(unittest.TestCase):
    def test_prestart_waits_for_first_anchor_plus_data_delay(self):
        now=START-timedelta(minutes=30)
        target=next_forecast_wake("early15m",now,[])
        self.assertGreater(target,START)
        self.assertLess((target-START).total_seconds(),120)

    def test_delayed_chain_inside_15m_deadline_retries_current_slot(self):
        now=START+timedelta(minutes=7)
        target=next_forecast_wake("early15m",now,[])
        self.assertGreater(target,now)
        self.assertLessEqual(target,START+timedelta(minutes=12))

    def test_after_15m_deadline_scheduler_advances_not_backfills(self):
        now=START+timedelta(minutes=14)
        target=next_forecast_wake("early15m",now,[])
        self.assertGreaterEqual(target,START+timedelta(minutes=16))
        self.assertLess(target,START+timedelta(minutes=18))

    def test_finalized_15m_slot_targets_next_anchor(self):
        slot=slot_text(START)
        now=START+timedelta(minutes=3)
        target=next_forecast_wake("early15m",now,[ev("forecast:"+slot)])
        self.assertGreater(target,START+timedelta(minutes=15))
        self.assertLess(target,START+timedelta(minutes=17))

    def test_hourly_chain_has_large_recovery_window(self):
        now=START+timedelta(minutes=20)
        target=next_forecast_wake("hourly",now,[])
        self.assertEqual(target,now+timedelta(minutes=2))

    def test_hourly_late_after_deadline_advances(self):
        now=START+timedelta(minutes=45)
        target=next_forecast_wake("hourly",now,[])
        self.assertGreater(target,START+timedelta(hours=1))

    def test_outcome_poll_is_after_next_boundary(self):
        now=START+timedelta(minutes=6)
        target=next_outcome_wake("early15m",now)
        self.assertEqual(target,START+timedelta(minutes=19))

    def test_finalized_accepts_missed_as_terminal(self):
        slot=slot_text(START)
        self.assertTrue(finalized_forecast([ev("missed:"+slot)],START))
        self.assertTrue(finalized_forecast([ev("forecast:"+slot)],START))
        self.assertFalse(finalized_forecast([],START))


if __name__=="__main__":
    unittest.main()
