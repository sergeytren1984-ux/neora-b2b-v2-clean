"""Regression tests for successor liveness decisions."""
from __future__ import annotations
import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))

from predictive_vnext4r6.chain_liveness import assess_runs


def run(run_id,status):
    return {"id":run_id,"status":status}


class ChainLivenessTests(unittest.TestCase):
    def test_self_mode_requires_other_live_run(self):
        a=assess_runs([run(10,"in_progress")],current_run_id=10)
        self.assertTrue(a["need_dispatch"])
        self.assertEqual(a["reason"],"NO_SUCCESSOR_FOR_CURRENT_RUN")

    def test_self_mode_accepts_pending_successor(self):
        a=assess_runs([run(10,"in_progress"),run(11,"pending")],current_run_id=10)
        self.assertFalse(a["need_dispatch"])
        self.assertEqual(a["other_live_count"],1)

    def test_completed_run_does_not_count_as_successor(self):
        a=assess_runs([run(10,"in_progress"),run(9,"completed")],current_run_id=10)
        self.assertTrue(a["need_dispatch"])

    def test_watchdog_repairs_running_without_successor(self):
        a=assess_runs([run(10,"in_progress")])
        self.assertTrue(a["need_dispatch"])
        self.assertEqual(a["reason"],"RUNNING_WITHOUT_SUCCESSOR")

    def test_watchdog_accepts_running_plus_queued(self):
        a=assess_runs([run(10,"in_progress"),run(11,"queued")])
        self.assertFalse(a["need_dispatch"])

    def test_watchdog_dispatches_when_chain_is_empty(self):
        a=assess_runs([run(9,"completed")])
        self.assertTrue(a["need_dispatch"])
        self.assertEqual(a["reason"],"NO_LIVE_RUN")

    def test_watchdog_does_not_duplicate_queued_recovery(self):
        a=assess_runs([run(11,"waiting")])
        self.assertFalse(a["need_dispatch"])
        self.assertEqual(a["reason"],"QUEUED_RUN_PRESENT")

    def test_unknown_status_is_not_live(self):
        a=assess_runs([run(10,"in_progress"),run(11,"mystery")],current_run_id=10)
        self.assertTrue(a["need_dispatch"])


if __name__=="__main__":
    unittest.main()
