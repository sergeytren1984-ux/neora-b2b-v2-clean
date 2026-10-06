"""Regression tests for the vNext4R6 unified long-lived scheduler."""
from __future__ import annotations

import json
import sys
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import call, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from predictive_vnext4r6.scheduler import (
    START,
    ACTIVE_SESSION_RUNTIME,
    PRESTART_SESSION_RUNTIME,
    FORECAST_DATA_DELAY,
    DEADLINE_SAFETY,
    RETRY_INTERVAL,
    forecast_attempt_targets,
    next_anchor_after,
    run_slot,
)
from predictive_vnext4r6.worker import (
    CONFIG,
    ensure_delivery_receipt,
    forecast,
    slot_text,
    signature_claim_args,
)


class SchedulerTests(unittest.TestCase):
    def test_unified_writer_per_head(self):
        self.assertEqual(set(CONFIG), {"1h", "4h", "24h"})
        for cfg in CONFIG.values():
            self.assertEqual(
                cfg["forecast_workflow"], cfg["outcome_workflow"]
            )

    def test_session_runtime(self):
        self.assertEqual(
            ACTIVE_SESSION_RUNTIME, timedelta(hours=4)
        )
        self.assertLess(
            PRESTART_SESSION_RUNTIME,
            timedelta(hours=5, minutes=30),
        )

    def test_data_delays_inside_deadlines(self):
        for head, cfg in CONFIG.items():
            self.assertGreater(
                FORECAST_DATA_DELAY[head], timedelta(0)
            )
            self.assertLess(
                FORECAST_DATA_DELAY[head], cfg["deadline"]
            )

    def test_prestart_anchor_is_frozen_start(self):
        for cfg in CONFIG.values():
            self.assertEqual(
                next_anchor_after(
                    START - timedelta(hours=1), cfg["cadence"]
                ),
                START,
            )

    def test_protocol_retry_and_signature_policy(self):
        for head, cfg in CONFIG.items():
            proto = json.loads(
                (ROOT / cfg["protocol"]).read_text()
            )
            self.assertEqual(proto["start_utc"], "2026-10-07T00:00:00Z")
            self.assertEqual(proto["selected_model"], "ensemble_equal")
            retry = proto["scheduler"]["transient_forecast_retry"]
            self.assertTrue(retry["enabled"])
            self.assertEqual(
                retry["delivery_safety_seconds"], 120
            )
            self.assertEqual(
                retry["retry_interval_seconds"],
                int(RETRY_INTERVAL[head].total_seconds()),
            )
            binding = proto["event_signature_binding"]
            self.assertTrue(
                binding[
                    "github_workflow_sha_must_equal_event_workflow_commit"
                ]
            )
            self.assertEqual(
                binding["github_workflow_ref"], "refs/heads/main"
            )
            self.assertEqual(
                binding["github_workflow_trigger"],
                "workflow_dispatch",
            )

    def test_retry_grid_multiple_attempts(self):
        self.assertEqual(
            DEADLINE_SAFETY, timedelta(minutes=2)
        )
        for head, cfg in CONFIG.items():
            targets = forecast_attempt_targets(head, START)
            self.assertGreaterEqual(len(targets), 2)
            cutoff = (
                START + cfg["deadline"] - DEADLINE_SAFETY
            )
            self.assertTrue(all(t < cutoff for t in targets))
            self.assertTrue(
                all(a < b for a, b in zip(targets, targets[1:]))
            )

    @patch("predictive_vnext4r6.scheduler.sleep_until")
    @patch("predictive_vnext4r6.scheduler.utcnow")
    @patch("predictive_vnext4r6.scheduler.invoke")
    def test_transient_failure_is_retried(
        self, mock_invoke, mock_now, _mock_sleep
    ):
        mock_now.return_value = START + timedelta(minutes=2)
        mock_invoke.side_effect = [False, None, True, None]
        self.assertTrue(run_slot("1h", START))
        self.assertEqual(
            mock_invoke.call_args_list,
            [
                call("1h", "forecast"),
                call("1h", "outcome"),
                call("1h", "forecast"),
                call("1h", "outcome"),
            ],
        )

    @patch(
        "predictive_vnext4r6.worker.ensure_delivery_receipt",
        return_value=True,
    )
    @patch("predictive_vnext4r6.worker.verify_signed_freeze")
    @patch("predictive_vnext4r6.worker.utcnow")
    def test_existing_forecast_repairs_receipt(
        self, mock_now, mock_verify, mock_ensure
    ):
        now = START + timedelta(minutes=2)
        mock_now.return_value = now
        slot = slot_text(START)
        event = {
            "type": "FORECAST_ISSUED",
            "sequence": 3,
            "slot": slot,
            "idempotency_key": "forecast:" + slot,
        }
        mock_verify.return_value = [(event, now)]
        self.assertTrue(forecast(CONFIG["1h"], "1h"))
        mock_ensure.assert_called_once()

    def test_signature_claim_binding(self):
        sha = "0123456789abcdef0123456789abcdef01234567"
        args = signature_claim_args(
            {"workflow_commit": sha}
        )
        self.assertEqual(
            args[args.index("--certificate-github-workflow-sha") + 1],
            sha,
        )
        for bad in ("", "abc", "g" * 40, "0" * 39):
            with self.assertRaises(ValueError):
                signature_claim_args({"workflow_commit": bad})

    @patch("predictive_vnext4r6.worker.utcnow")
    @patch(
        "predictive_vnext4r6.worker.prior_events",
        return_value=[],
    )
    def test_receipt_cannot_recover_inside_safety_margin(
        self, _mock_prior, mock_now
    ):
        cfg = CONFIG["1h"]
        deadline = START + cfg["deadline"]
        mock_now.return_value = deadline - timedelta(seconds=30)
        slot = slot_text(START)
        event = {
            "type": "FORECAST_ISSUED",
            "sequence": 3,
            "slot": slot,
            "idempotency_key": "forecast:" + slot,
        }
        self.assertFalse(
            ensure_delivery_receipt(cfg, event, deadline)
        )


if __name__ == "__main__":
    unittest.main()
