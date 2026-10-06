"""Defensive regression tests for the vNext4R6 scorecard."""
from __future__ import annotations

import copy
import json
import sys
import unittest
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from predictive_vnext4r6.scorecard import (
    START,
    distribution,
    score_from_events,
)
from predictive_vnext4r6.worker import CONFIG, slot_text


def forecast(slot, anchor, primary=None, model=None, vol_bin=1):
    if model is None:
        model = {
            "lower_first": 0.70,
            "upper_first": 0.10,
            "neither": 0.19,
            "ambiguous_same_bar": 0.01,
        }
    if primary is None:
        primary = {
            "lower_first": 0.25,
            "upper_first": 0.25,
            "neither": 0.49,
            "ambiguous_same_bar": 0.01,
        }
    return {
        "type": "FORECAST_ISSUED",
        "slot": slot,
        "anchor_utc": anchor.isoformat(),
        "class_distribution": model,
        "control": {
            "primary_distribution": primary,
            "volatility_bin": vol_bin,
        },
    }


def outcome(slot, cls="LOWER_FIRST"):
    return {
        "type": "OUTCOME_RECORDED",
        "slot": slot,
        "outcome_class": cls,
    }


def receipt(slot):
    return {
        "type": "DELIVERY_CONFIRMED",
        "slot": slot,
    }


class ScorecardTests(unittest.TestCase):
    def protocol(self, head="1h"):
        proto = json.loads(
            (ROOT / CONFIG[head]["protocol"]).read_text()
        )
        proto = copy.deepcopy(proto)
        proto["admission"]["minimum_calendar_days"] = 0
        proto["admission"][
            "minimum_fixed_phase_nonoverlap_windows"
        ] = 1
        proto["admission"][
            "minimum_independent_volatility_episodes"
        ] = 1
        proto["admission"]["require_all_three_volatility_bins"] = False
        return proto

    def test_distribution_rejects_bad_probability_vectors(self):
        with self.assertRaises(ValueError):
            distribution(
                {
                    "lower_first": 0.6,
                    "upper_first": 0.6,
                    "neither": 0.0,
                    "ambiguous_same_bar": 0.0,
                }
            )
        with self.assertRaises(ValueError):
            distribution(
                {
                    "lower_first": -0.1,
                    "upper_first": 0.2,
                    "neither": 0.9,
                    "ambiguous_same_bar": 0.0,
                }
            )

    def test_missing_forecast_or_outcome_blocks_complete_grid(self):
        proto = self.protocol()
        cutoff = START + timedelta(hours=1, minutes=1)
        slot = slot_text(START)
        events = [
            forecast(slot, START),
            receipt(slot),
        ]
        result = score_from_events(
            events, proto, cutoff, allow_admission=True
        )
        self.assertFalse(result["complete_due_grid"])
        self.assertFalse(result["admission_ready"])
        self.assertIn(slot, result["missing_due_nonoverlap_slots"])

    def test_missing_delivery_receipt_blocks_grid(self):
        proto = self.protocol()
        cutoff = START + timedelta(hours=1, minutes=1)
        slot = slot_text(START)
        events = [
            forecast(slot, START),
            outcome(slot),
        ]
        result = score_from_events(
            events, proto, cutoff, allow_admission=True
        )
        self.assertFalse(result["complete_due_grid"])
        self.assertFalse(result["admission_ready"])

    def test_diagnostic_cutoff_never_admits(self):
        proto = self.protocol()
        cutoff = START + timedelta(hours=1, minutes=1)
        slot = slot_text(START)
        events = [
            forecast(slot, START),
            outcome(slot),
            receipt(slot),
        ]
        result = score_from_events(
            events, proto, cutoff, allow_admission=False
        )
        self.assertEqual(
            result["evaluation_mode"],
            "HISTORICAL_DIAGNOSTIC_ONLY",
        )
        self.assertFalse(result["admission_ready"])

    def test_current_mode_requires_statistical_ci_not_just_one_win(self):
        proto = self.protocol()
        cutoff = START + timedelta(hours=1, minutes=1)
        slot = slot_text(START)
        events = [
            forecast(slot, START),
            outcome(slot),
            receipt(slot),
        ]
        result = score_from_events(
            events, proto, cutoff, allow_admission=True
        )
        self.assertTrue(result["complete_due_grid"])
        self.assertFalse(result["admission_ready"])
        self.assertFalse(result["gates"]["block_ci"])

    def test_fixed_phase_uses_head_horizon_grid(self):
        proto = self.protocol("4h")
        cutoff = START + timedelta(hours=4, minutes=1)
        slot = slot_text(START)
        events = [
            forecast(slot, START),
            outcome(slot),
            receipt(slot),
        ]
        result = score_from_events(
            events, proto, cutoff, allow_admission=True
        )
        self.assertEqual(result["expected_due_nonoverlap_windows"], 1)
        self.assertEqual(result["complete_due_nonoverlap_windows"], 1)


if __name__ == "__main__":
    unittest.main()
