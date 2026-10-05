"""Regression tests for vNext4R5 admission completeness and prior audit defects."""
from __future__ import annotations

import unittest
import sys
from unittest.mock import patch
from pathlib import Path
from datetime import datetime,timedelta,timezone

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))

from predictive_vnext4r5.scorecard import (score,signature_claim_args,canonical,digest,duplicate_slot_rejections,schedule_registration_rejections)

UTC=timezone.utc
START=datetime(2026,10,5,15,0,tzinfo=UTC)
MODELS=("logistic","gbdt","competing_risks")


def d(p):
    return {"lower_first":p[0],"upper_first":p[1],"neither":p[2],"ambiguous_same_bar":p[3]}


def contender(pred):
    return {m:{"class_distribution":d(pred),
               "alerts_at_calibration_fpr20":{
                   "lower_first":False,"upper_first":False,
                   "lower_threshold":.5,"upper_threshold":.5}}
            for m in MODELS}


def add_pair(events,a,hours,actual,pred,base,vol_bin,include_outcome=True):
    slot=a.strftime("%Y%m%dT%H%M%SZ");due=a+timedelta(hours=hours)
    events.append({
        "type":"FORECAST_ISSUED","slot":slot,"anchor_utc":a.isoformat(),
        "due_utc":due.isoformat(),
        "control":{"primary_distribution":d(base),"secondary_distribution":d(base),
                   "volatility_bin":vol_bin},
        "contenders":contender(pred)
    })
    if include_outcome:
        cls=("LOWER_FIRST","UPPER_FIRST","NEITHER","AMBIGUOUS_SAME_BAR")[actual]
        events.append({
            "type":"OUTCOME_RECORDED","slot":slot,"anchor_utc":a.isoformat(),
            "due_utc":due.isoformat(),"published_at_utc":(due+timedelta(minutes=5)).isoformat(),
            "outcome_class":cls,"first_touch_time_utc":None
        })


class SignatureBindingRegressionTests(unittest.TestCase):
    def test_scorecard_signature_claims_bind_exact_workflow_sha(self):
        sha="89abcdef0123456789abcdef0123456789abcdef"
        args=signature_claim_args({"workflow_commit":sha})
        self.assertEqual(args[args.index("--certificate-github-workflow-sha")+1],sha)
        self.assertEqual(
            args[args.index("--certificate-github-workflow-repository")+1],
            "sergeytren1984-ux/neora-b2b-v2-clean",
        )
        self.assertEqual(args[args.index("--certificate-github-workflow-ref")+1],"refs/heads/main")
        self.assertEqual(args[args.index("--certificate-github-workflow-trigger")+1],"workflow_dispatch")

    def test_scorecard_signature_claims_reject_malformed_sha(self):
        for bad in ("", "1234", "z"*40, "0"*41):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    signature_claim_args({"workflow_commit":bad})


class AdmissionRegressionTests(unittest.TestCase):
    def test_overlapping_wins_cannot_override_nonoverlap_losses(self):
        events=[]
        # Create 92 days of hourly forecasts; fixed 72h phase anchors are bad.
        for i in range(92*24):
            a=START+timedelta(hours=i);actual=i%3
            base=[.20,.20,.60,0.0]
            if i%72==0:
                pred=[.90,.05,.05,0.0] if actual!=0 else [.05,.90,.05,0.0]
            else:
                pred=[.02,.02,.02,.02];pred[actual]=.94
            add_pair(events,a,72,actual,pred,base,(i//72)%3,True)
        as_of=START+timedelta(days=92,hours=72)
        result=score(events,"hourly",72,90,30,12,as_of_utc=as_of)
        self.assertFalse(result["admission_ready"])
        for m in MODELS:
            self.assertFalse(result["contenders"][m]["passes_all"])
            self.assertGreater(result["contenders"][m]["nonoverlap"]["brier"],
                               result["primary_baseline_nonoverlap"]["brier"])

    def test_episode_gate_uses_independent_windows(self):
        events=[]
        for i in range(100*24):
            a=START+timedelta(hours=i);b=0 if i%72==0 else i%3
            add_pair(events,a,72,2,[.25,.25,.49,.01],[.25,.25,.49,.01],b,True)
        as_of=START+timedelta(days=100,hours=72)
        result=score(events,"hourly",72,90,30,12,as_of_utc=as_of)
        self.assertEqual(result["volatility_bins_seen_nonoverlap"],[0])
        self.assertEqual(result["independent_volatility_episode_count"],1)
        self.assertFalse(result["admission_ready"])

    def test_missing_bad_outcomes_cannot_create_false_admission(self):
        # Exact exploit from the independent audit: 420 due 4h independent slots
        # over 70 days, but outcomes are recorded only for the 210 successful cases.
        events=[]
        total=420
        for i in range(total):
            a=START+timedelta(hours=4*i)
            actual=i%2
            base=[.25,.25,.49,.01]
            if i%2==0:
                # Recorded half: candidate looks excellent.
                pred=[.94,.02,.02,.02] if actual==0 else [.02,.94,.02,.02]
                include=True
            else:
                # Missing half would make candidate poor if observed.
                pred=[.94,.02,.02,.02] if actual!=0 else [.02,.94,.02,.02]
                include=False
            add_pair(events,a,4,actual,pred,base,(i//5)%3,include)
        as_of=START+timedelta(hours=4*total)
        result=score(events,"early15m",4,42,150,12,as_of_utc=as_of)
        comp=result["outcome_completeness"]
        self.assertEqual(comp["expected_due_independent_slots"],420)
        self.assertEqual(comp["complete_due_independent_slots"],210)
        self.assertEqual(comp["missing_outcome_count"],210)
        self.assertFalse(comp["complete"])
        self.assertFalse(result["admission_ready"])
        for m in MODELS:
            self.assertFalse(result["contenders"][m]["gates"]["complete_due_grid"])
            self.assertFalse(result["contenders"][m]["passes_all"])

    def test_missing_forecast_on_due_grid_is_permanent_admission_block(self):
        events=[]
        # 180 due 4h windows, deliberately omit one forecast entirely.
        total=180
        for i in range(total):
            if i==73:
                continue
            a=START+timedelta(hours=4*i)
            add_pair(events,a,4,2,[.05,.05,.88,.02],[.20,.20,.58,.02],(i//4)%3,True)
        as_of=START+timedelta(hours=4*total)
        result=score(events,"early15m",4,42,150,12,as_of_utc=as_of)
        self.assertEqual(result["outcome_completeness"]["missing_forecast_count"],1)
        self.assertFalse(result["admission_ready"])


    def test_historical_cutoff_can_never_claim_current_admission(self):
        # Reproduce the independent expert's attack: 420 forecasts exist,
        # outcomes exist only through the first 360 due fixed-phase windows.
        # The old 360-window cutoff is statistically admissible, but it must be
        # diagnostic-only once supplied manually.
        events=[]
        total=420
        closed=360
        for i in range(total):
            a=START+timedelta(hours=4*i)
            include=i<closed
            add_pair(events,a,4,2,[.01,.01,.97,.01],[.25,.25,.25,.25],i%3,include)
        old_cutoff=START+timedelta(hours=4*closed)
        historical=score(events,"early15m",4,42,150,12,as_of_utc=old_cutoff)
        self.assertEqual(historical["evaluation_mode"],"HISTORICAL_DIAGNOSTIC")
        self.assertTrue(historical["historical_candidate_ready"])
        self.assertFalse(historical["admission_ready"])
        self.assertIsNone(historical["prospective_winner"])
        self.assertIn(historical["historical_counterfactual_winner"],MODELS)

        current_cutoff=START+timedelta(hours=4*total)
        with patch("predictive_vnext4r5.scorecard.utcnow",return_value=current_cutoff):
            current=score(events,"early15m",4,42,150,12)
        self.assertEqual(current["evaluation_mode"],"CURRENT_TRUSTED_CLOCK")
        self.assertEqual(current["outcome_completeness"]["missing_outcome_count"],total-closed)
        self.assertFalse(current["admission_ready"])

    def test_duplicate_forecast_same_slot_is_never_silently_overwritten(self):
        events=[]
        a=START
        add_pair(events,a,4,2,[.01,.01,.97,.01],[.25,.25,.25,.25],0,True)
        duplicate=dict(events[0])
        duplicate["idempotency_key"]="different-key"
        events.append(duplicate)
        result=score(events,"early15m",4,42,150,12,as_of_utc=START+timedelta(hours=4))
        self.assertEqual(result["status"],"INVALID_DUPLICATE_SLOT_EVENTS")
        self.assertEqual(result["duplicate_forecast_slots"],[START.strftime("%Y%m%dT%H%M%SZ")])
        self.assertFalse(result["admission_ready"])
        rejected=duplicate_slot_rejections(events)
        self.assertTrue(any(x["reason"]=="duplicate_event_type_slot" for x in rejected))

    def test_schedule_registration_semantics_are_strict(self):
        protocol={
            "head":"early15m_pm1pct_4h",
            "start_utc":START.isoformat(),
            "issuance_deadline_minutes":14,
            "admission":{"expected_grid_phase_utc":START.isoformat()},
        }
        protocol_bytes=b"frozen protocol bytes\n"
        source="1"*40
        schedule={
            "type":"SCHEDULE_REGISTERED","sequence":1,
            "idempotency_key":"early15m:schedule",
            "source_commit_sha":source,
            "start_utc":START.isoformat(),
            "deadline_minutes":14,
            "protocol_sha256":digest(protocol_bytes),
            "trading_authority":False,
        }
        freeze={"type":"CONFIG_FROZEN_PRESTART","sequence":2}
        rekor={1:START-timedelta(minutes=10)}
        self.assertEqual(
            schedule_registration_rejections([schedule,freeze],rekor,source,protocol,protocol_bytes,freeze),
            []
        )
        bad=dict(schedule);bad["source_commit_sha"]="2"*40
        rejected=schedule_registration_rejections([bad,freeze],rekor,source,protocol,protocol_bytes,freeze)
        self.assertTrue(any(x["reason"]=="schedule_source_commit_mismatch" for x in rejected))

    def test_no_due_grid_cannot_admit(self):
        result=score([],"early15m",4,42,150,12,
                     as_of_utc=START+timedelta(hours=3,minutes=59))
        self.assertEqual(result["status"],"PENDING_NO_DUE_INDEPENDENT_WINDOWS")
        self.assertFalse(result["admission_ready"])


if __name__=="__main__":
    unittest.main()
