"""Regression tests for the R3 unified long-lived scheduler."""
from __future__ import annotations
import sys,unittest
from pathlib import Path
from datetime import timedelta
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))

from predictive_vnext4r3.scheduler import (
    START,SESSION_SLOTS,FORECAST_DATA_DELAY,next_anchor_after
)
from predictive_vnext4r3.worker import CONFIG

class SchedulerTests(unittest.TestCase):
    def test_unified_writer_per_head(self):
        for head,cfg in CONFIG.items():
            self.assertEqual(cfg["forecast_workflow"],cfg["outcome_workflow"])

    def test_sessions_cover_four_hours(self):
        self.assertEqual(SESSION_SLOTS["early15m"],16)
        self.assertEqual(SESSION_SLOTS["hourly"],4)

    def test_first_wake_is_after_closed_candle(self):
        self.assertGreater(FORECAST_DATA_DELAY["early15m"],timedelta(seconds=0))
        self.assertLess(FORECAST_DATA_DELAY["early15m"],CONFIG["early15m"]["deadline"])
        self.assertGreater(FORECAST_DATA_DELAY["hourly"],timedelta(seconds=0))
        self.assertLess(FORECAST_DATA_DELAY["hourly"],CONFIG["hourly"]["deadline"])

    def test_prestart_anchor_is_frozen_start(self):
        self.assertEqual(next_anchor_after(START-timedelta(hours=1),CONFIG["early15m"]["cadence"]),START)

    def test_current_slot_recovery_anchor(self):
        now=START+timedelta(minutes=7)
        self.assertEqual(next_anchor_after(now,CONFIG["early15m"]["cadence"]),START)

if __name__=="__main__":
    unittest.main()
