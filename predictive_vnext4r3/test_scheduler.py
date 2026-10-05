"""Regression tests for the R3 unified long-lived scheduler."""
from __future__ import annotations
import sys,unittest
from unittest.mock import call,patch
from pathlib import Path
from datetime import timedelta
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))

from predictive_vnext4r3.scheduler import (
    START,ACTIVE_SESSION_RUNTIME,PRESTART_SESSION_RUNTIME,FORECAST_DATA_DELAY,
    DEADLINE_SAFETY,RETRY_INTERVAL,forecast_attempt_targets,next_anchor_after,run_slot
)
from predictive_vnext4r3.worker import CONFIG,ensure_delivery_receipt,forecast,slot_text,signature_claim_args

class SchedulerTests(unittest.TestCase):
    def test_unified_writer_per_head(self):
        for head,cfg in CONFIG.items():
            self.assertEqual(cfg["forecast_workflow"],cfg["outcome_workflow"])

    def test_active_session_runtime_is_four_hours(self):
        self.assertEqual(ACTIVE_SESSION_RUNTIME,timedelta(hours=4))
        self.assertLess(PRESTART_SESSION_RUNTIME,timedelta(hours=5,minutes=30))

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


    def test_retry_grid_has_multiple_attempts_strictly_before_deadline(self):
        for head,cfg in CONFIG.items():
            targets=forecast_attempt_targets(head,START)
            self.assertGreaterEqual(len(targets),2)
            self.assertEqual(targets[0],START+FORECAST_DATA_DELAY[head])
            cutoff=START+cfg["deadline"]-DEADLINE_SAFETY
            self.assertTrue(all(a<b for a,b in zip(targets,targets[1:])))
            self.assertTrue(all(t<cutoff for t in targets))
            self.assertGreater(RETRY_INTERVAL[head],timedelta(0))

    @patch("predictive_vnext4r3.scheduler.sleep_until")
    @patch("predictive_vnext4r3.scheduler.utcnow")
    @patch("predictive_vnext4r3.scheduler.invoke")
    def test_transient_forecast_failure_is_retried(self,mock_invoke,mock_now,_mock_sleep):
        mock_now.return_value=START+timedelta(minutes=2)
        mock_invoke.side_effect=[False,None,True,None]
        self.assertTrue(run_slot("early15m",START))
        self.assertEqual(mock_invoke.call_args_list,[
            call("early15m","forecast"),call("early15m","outcome"),
            call("early15m","forecast"),call("early15m","outcome"),
        ])

    @patch("predictive_vnext4r3.worker.ensure_delivery_receipt",return_value=True)
    @patch("predictive_vnext4r3.worker.verify_signed_freeze")
    @patch("predictive_vnext4r3.worker.utcnow")
    def test_existing_forecast_repairs_missing_delivery_receipt(self,mock_now,mock_verify,mock_ensure):
        now=START+timedelta(minutes=2)
        mock_now.return_value=now
        slot=slot_text(START)
        event={"type":"FORECAST_ISSUED","sequence":3,"slot":slot,
               "idempotency_key":"forecast:"+slot}
        mock_verify.return_value=[(event,now)]
        self.assertTrue(forecast(CONFIG["early15m"],"early15m"))
        mock_ensure.assert_called_once()
        args=mock_ensure.call_args.args
        self.assertEqual(args[1],event)
        self.assertEqual(args[2],START+CONFIG["early15m"]["deadline"])

    def test_signature_claims_bind_event_to_exact_workflow_sha(self):
        sha="0123456789abcdef0123456789abcdef01234567"
        args=signature_claim_args({"workflow_commit":sha})
        self.assertIn("--certificate-github-workflow-sha",args)
        self.assertEqual(args[args.index("--certificate-github-workflow-sha")+1],sha)
        self.assertIn("--certificate-github-workflow-repository",args)
        self.assertIn("--certificate-github-workflow-ref",args)
        self.assertIn("--certificate-github-workflow-trigger",args)

    def test_signature_claims_reject_missing_or_malformed_workflow_sha(self):
        for bad in ("","abc","g"*40,"0"*39):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    signature_claim_args({"workflow_commit":bad})

    @patch("predictive_vnext4r3.worker.utcnow")
    @patch("predictive_vnext4r3.worker.prior_events",return_value=[])
    def test_delivery_receipt_cannot_be_recovered_inside_safety_margin(self,_mock_prior,mock_now):
        cfg=CONFIG["early15m"]
        deadline=START+cfg["deadline"]
        mock_now.return_value=deadline-timedelta(seconds=30)
        slot=slot_text(START)
        event={"type":"FORECAST_ISSUED","sequence":3,"slot":slot,
               "idempotency_key":"forecast:"+slot}
        self.assertFalse(ensure_delivery_receipt(cfg,event,deadline))

if __name__=="__main__":
    unittest.main()
