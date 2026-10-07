"""Adversarial regression tests for the R7.1 blockers found by independent audit."""
from __future__ import annotations

import ast
import inspect
import json
import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from predictive_vnext4r7.integrity import canonical, digest
from predictive_vnext4r7.scorecard_core import score_from_events
from predictive_vnext4r71.admission import (
    _assert_remote_tip_still_exact,
    _verify_checkout_path_at_head,
    _verify_exact_checkout_remote_tip,
    run_admission,
)
from predictive_vnext4r71.checkpoint import git_prefix_binding
from predictive_vnext4r71.integrity import (
    REQUIRED_PROTOCOLS,
    REQUIRED_PRODUCTION_WORKFLOWS,
    safe_repo_relative_path,
    validate_event_collection,
    verify_deployment_bundle_against_manifest,
)
from predictive_vnext4r71.tail_research import (
    monotone_exceedance,
    monotone_quantiles,
    quantile_crossings,
    threshold_order_violations,
    research_gate,
)
from predictive_vnext4r7.episodes import stress_episode_skill_summary
from predictive_vnext4r71 import worker
from predictive_vnext4r71 import chain_liveness

UTC = timezone.utc


def _base_event(seq, prev, et, slot=None):
    e = {
        "schema": "btc-predictive-vnext4r71-event-v1",
        "sequence": seq,
        "previous_hash": prev,
        "workflow_commit": "1" * 40,
        "published_at_utc": "2026-10-07T00:00:01+00:00",
        "type": et,
        "head": "1h",
        "trading_authority": False,
    }
    if et == "SCHEDULE_REGISTERED":
        e.update({
            "idempotency_key": "1h:schedule",
            "start_utc": "2026-10-07T00:00:00+00:00",
            "deadline_minutes": 14,
            "protocol_sha256": "2" * 64,
            "source_commit_sha": "3" * 40,
        })
    elif et == "CONFIG_FROZEN_PRESTART":
        manifest={"source_commit_sha":"3"*40,"paths_sha256":{}}
        e.update({
            "idempotency_key": "1h:freeze",
            "start_utc": "2026-10-07T00:00:00+00:00",
            "manifest": manifest,
            "manifest_sha256": digest(canonical(manifest)),
        })
    else:
        e["slot"] = slot
    return e


def valid_chain(include_outcome=True):
    events=[]
    prev=None
    s=_base_event(1,prev,"SCHEDULE_REGISTERED"); events.append(s); prev=digest(canonical(s))
    fz=_base_event(2,prev,"CONFIG_FROZEN_PRESTART"); events.append(fz); prev=digest(canonical(fz))
    slot="20261007T010000Z"
    fc=_base_event(3,prev,"FORECAST_ISSUED",slot)
    fc.update({
        "idempotency_key":"forecast:"+slot,
        "anchor_utc":"2026-10-07T01:00:00+00:00",
        "due_utc":"2026-10-07T02:00:00+00:00",
        "published_at_utc":"2026-10-07T01:01:00+00:00",
        "lower_price":99.0,"upper_price":101.0,
        "artifact_sha256":"a"*64,"baseline_sha256":"b"*64,
        "raw_path":"raw/f.json","raw_sha256":"c"*64,
        "class_distribution":{"lower_first":.25,"upper_first":.25,"neither":.5,"ambiguous_same_bar":0.0},
        "control":{"primary_distribution":{"lower_first":.25,"upper_first":.25,"neither":.5,"ambiguous_same_bar":0.0},"volatility_bin":1},
    })
    events.append(fc); prev=digest(canonical(fc))
    rc=_base_event(4,prev,"DELIVERY_CONFIRMED",slot)
    rc.update({
        "idempotency_key":"delivery:forecast:"+slot,
        "target_sequence":3,
        "target_event_hash":digest(canonical(fc)),
        "remote_commit_sha":"4"*40,
        "remote_confirmed_at_utc":"2026-10-07T01:02:00+00:00",
        "deadline_utc":"2026-10-07T01:14:00+00:00",
        "published_at_utc":"2026-10-07T01:02:00+00:00",
    })
    events.append(rc); prev=digest(canonical(rc))
    if include_outcome:
        oc=_base_event(5,prev,"OUTCOME_RECORDED",slot)
        oc.update({
            "idempotency_key":"outcome:"+slot,
            "anchor_utc":"2026-10-07T01:00:00+00:00",
            "due_utc":"2026-10-07T02:00:00+00:00",
            "published_at_utc":"2026-10-07T02:01:00+00:00",
            "outcome_class":"LOWER_FIRST",
            "first_touch_time_utc":"2026-10-07T01:30:00+00:00",
            "lower_price":99.0,"upper_price":101.0,
            "raw_path":"raw/o.json","raw_sha256":"d"*64,
        })
        events.append(oc)
    return events


def _commit_protocol(root: Path, obj: dict) -> tuple[Path, str]:
    subprocess.run(["git","init"],cwd=root,check=True,capture_output=True)
    subprocess.run(["git","config","user.email","x@example.com"],cwd=root,check=True)
    subprocess.run(["git","config","user.name","x"],cwd=root,check=True)
    p=root/"protocol.json"
    p.write_bytes(canonical(obj))
    subprocess.run(["git","add","protocol.json"],cwd=root,check=True)
    subprocess.run(["git","commit","-m","protocol"],cwd=root,check=True,capture_output=True)
    head=subprocess.run(
        ["git","rev-parse","HEAD"],cwd=root,check=True,capture_output=True,text=True
    ).stdout.strip()
    return p,head


class EventInvariantTests(unittest.TestCase):
    def test_valid_relations_pass(self):
        out=validate_event_collection(
            valid_chain(),
            head="1h",
            horizon=timedelta(hours=1),
            issuance_deadline=timedelta(minutes=14),
        )
        self.assertEqual(out["forecast_count"],1)

    def test_wrong_receipt_target_rejected(self):
        events=valid_chain()
        events[3]["target_sequence"]=999
        with self.assertRaises(ValueError):
            validate_event_collection(events,head="1h",horizon=timedelta(hours=1),issuance_deadline=timedelta(minutes=14))

    def test_early_outcome_rejected(self):
        events=valid_chain()
        events[4]["published_at_utc"]="2026-10-07T01:59:59+00:00"
        with self.assertRaises(ValueError):
            validate_event_collection(events,head="1h",horizon=timedelta(hours=1),issuance_deadline=timedelta(minutes=14))

    def test_unknown_type_rejected(self):
        events=valid_chain(False)
        bad=_base_event(5,digest(canonical(events[-1])),"ALIEN_EVENT","20261007T020000Z")
        bad["idempotency_key"]="alien"
        events.append(bad)
        with self.assertRaises(ValueError):
            validate_event_collection(events,head="1h",horizon=timedelta(hours=1),issuance_deadline=timedelta(minutes=14))

    def test_head_none_rejected(self):
        events=valid_chain()
        events[2]["head"]=None
        with self.assertRaises(ValueError):
            validate_event_collection(events,head="1h",horizon=timedelta(hours=1),issuance_deadline=timedelta(minutes=14))


class AdmissionBoundaryTests(unittest.TestCase):
    def test_direct_numerical_admission_forbidden(self):
        with self.assertRaises(RuntimeError):
            score_from_events(
                [],{"head":"1h"},
                start_utc=datetime(2026,10,7,tzinfo=UTC),
                horizon=timedelta(hours=1),
                allow_admission=True,
            )

    def test_public_admission_has_no_verifier_or_tip_override(self):
        params=inspect.signature(run_admission).parameters
        self.assertNotIn("verify_forecast_blob",params)
        self.assertNotIn("verify_outcome_blob",params)
        self.assertNotIn("current_tip",params)

    def test_disabled_signed_protocol_blocks_before_scoring(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            _commit_protocol(root,{"admission_enabled":False,"head":"1h"})
            out=run_admission(
                repo_root=str(root),
                protocol_path="protocol.json",
                events_dir="events",
            )
            self.assertFalse(out["admission_ready"])
            self.assertEqual(out["status"],"BLOCKED_PROTOCOL_ADMISSION_DISABLED")

    def test_diagnostic_cutoff_is_rejected_before_replay(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            _commit_protocol(root,{
                "admission_enabled":True,
                "head":"1h",
                "diagnostic_cutoff_utc":"2026-10-07T00:00:00Z",
            })
            with self.assertRaisesRegex(
                ValueError,"non-prospective admission control forbidden"
            ):
                run_admission(
                    repo_root=str(root),
                    protocol_path="protocol.json",
                    events_dir="events",
                )

    def test_historical_mode_is_rejected_before_replay(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            _commit_protocol(root,{
                "admission_enabled":True,
                "head":"1h",
                "mode":"HISTORICAL",
            })
            with self.assertRaisesRegex(
                ValueError,"non-prospective admission mode forbidden"
            ):
                run_admission(
                    repo_root=str(root),
                    protocol_path="protocol.json",
                    events_dir="events",
                )


class ExactCheckoutBindingTests(unittest.TestCase):
    def test_stale_checkout_cannot_claim_new_remote_tip(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/"work"
            bare=Path(td)/"remote.git"
            root.mkdir()
            subprocess.run(["git","init","--bare",str(bare)],check=True,capture_output=True)
            subprocess.run(["git","init"],cwd=root,check=True,capture_output=True)
            subprocess.run(["git","config","user.email","x@example.com"],cwd=root,check=True)
            subprocess.run(["git","config","user.name","x"],cwd=root,check=True)
            subprocess.run(["git","remote","add","origin",str(bare)],cwd=root,check=True)
            (root/"a.txt").write_text("a")
            subprocess.run(["git","add","a.txt"],cwd=root,check=True)
            subprocess.run(["git","commit","-m","A"],cwd=root,check=True,capture_output=True)
            a=subprocess.run(
                ["git","rev-parse","HEAD"],cwd=root,check=True,
                capture_output=True,text=True,
            ).stdout.strip()
            subprocess.run(["git","branch","-M","evidence"],cwd=root,check=True)
            subprocess.run(
                ["git","push","-u","origin","evidence"],
                cwd=root,check=True,capture_output=True,
            )
            (root/"b.txt").write_text("b")
            subprocess.run(["git","add","b.txt"],cwd=root,check=True)
            subprocess.run(["git","commit","-m","B"],cwd=root,check=True,capture_output=True)
            subprocess.run(
                ["git","push","origin","evidence"],
                cwd=root,check=True,capture_output=True,
            )
            subprocess.run(["git","checkout","--detach",a],cwd=root,check=True,capture_output=True)
            with self.assertRaisesRegex(
                ValueError,
                "admission checkout HEAD is not exact fetched remote evidence tip",
            ):
                _verify_exact_checkout_remote_tip(root,"evidence")

    def test_remote_tip_advance_during_admission_is_fail_closed(self):
        expected="a"*40
        with patch(
            "predictive_vnext4r71.admission._verify_exact_checkout_remote_tip",
            return_value="b"*40,
        ):
            with self.assertRaisesRegex(
                ValueError,"remote evidence tip changed during scoring"
            ):
                _assert_remote_tip_still_exact(
                    Path("."),
                    "evidence",
                    expected,
                    phase="during scoring",
                )

    def test_working_tree_protocol_mutation_cannot_change_used_policy(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            p,head=_commit_protocol(root,{
                "admission_enabled":False,
                "head":"1h",
                "selected_model":"SIGNED_MODEL",
            })
            signed_bytes=subprocess.run(
                ["git","show",f"{head}:protocol.json"],
                cwd=root,check=True,capture_output=True,
            ).stdout
            p.write_bytes(canonical({
                "admission_enabled":True,
                "head":"1h",
                "selected_model":"UNSIGNED_ATTACKER_CHOICE",
                "admission":{"minimum_calendar_days":0},
            }))
            out=run_admission(
                repo_root=str(root),protocol_path="protocol.json",events_dir="events"
            )
            self.assertEqual(out["status"],"BLOCKED_PROTOCOL_ADMISSION_DISABLED")
            self.assertTrue(out["governance"]["authenticated_protocol_snapshot"])
            self.assertEqual(
                out["governance"]["used_protocol_sha256"],digest(signed_bytes)
            )
            self.assertFalse(
                out["governance"]["decision_binding"]["absolute_latest_tip_atomicity_claimed"]
            )

    def test_working_tree_bytes_must_equal_exact_head(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            subprocess.run(["git","init"],cwd=root,check=True,capture_output=True)
            subprocess.run(["git","config","user.email","x@example.com"],cwd=root,check=True)
            subprocess.run(["git","config","user.name","x"],cwd=root,check=True)
            p=root/"x.json"
            p.write_text('{"x":1}\n')
            subprocess.run(["git","add","x.json"],cwd=root,check=True)
            subprocess.run(["git","commit","-m","x"],cwd=root,check=True,capture_output=True)
            head=subprocess.run(
                ["git","rev-parse","HEAD"],cwd=root,check=True,
                capture_output=True,text=True,
            ).stdout.strip()
            _verify_checkout_path_at_head(root,head,"x.json")
            p.write_text('{"x":2}\n')
            with self.assertRaisesRegex(
                ValueError,"working-tree bytes differ from exact checkout HEAD"
            ):
                _verify_checkout_path_at_head(root,head,"x.json")


class CheckpointGitBindingTests(unittest.TestCase):
    def test_claimed_sequence_must_exist_in_verified_commit_with_bundles(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            subprocess.run(["git","init"],cwd=root,check=True,capture_output=True)
            subprocess.run(["git","config","user.email","x@example.com"],cwd=root,check=True)
            subprocess.run(["git","config","user.name","x"],cwd=root,check=True)
            d=root/"events"; d.mkdir()
            for i in range(1,24):
                (d/f"{i:08d}.json").write_text("{}\n")
                (d/f"{i:08d}.sigstore.json").write_text("{}\n")
            subprocess.run(["git","add","."],cwd=root,check=True)
            subprocess.run(["git","commit","-m","23"],cwd=root,check=True,capture_output=True)
            commit=subprocess.run(["git","rev-parse","HEAD"],cwd=root,check=True,capture_output=True,text=True).stdout.strip()

            # Event #24 exists only in the working tree, exactly the audit attack.
            (d/"00000024.json").write_text("{}\n")
            (d/"00000024.sigstore.json").write_text("{}\n")
            with self.assertRaises(ValueError):
                git_prefix_binding(root,d,commit,24)


class TailCoherenceTests(unittest.TestCase):
    def test_quantile_projection_removes_crossings(self):
        raw=np.asarray([[2.0,1.0,3.0],[1.0,4.0,2.0]])
        self.assertGreater(quantile_crossings(raw),0)
        projected=monotone_quantiles(raw)
        self.assertEqual(quantile_crossings(projected),0)

    def test_threshold_projection_removes_order_violations(self):
        raw=np.asarray([[.3,.5,.1],[.8,.4,.6]])
        self.assertGreater(threshold_order_violations(raw),0)
        projected=monotone_exceedance(raw)
        self.assertEqual(threshold_order_violations(projected),0)

    def test_q3_diagnostic_cannot_change_research_gate(self):
        side={
            "thresholds":{
                "1.0":{"selection_2026h1":{"brier":.1,"baseline_brier":.2}},
                "1.5":{"selection_2026h1":{"brier":.1,"baseline_brier":.2}},
                "2.0":{"selection_2026h1":{"brier":.3,"baseline_brier":.2}},
            },
            "quantiles":{
                "0.9":{"selection_2026h1":{
                    "pinball":.1,
                    "baseline_pinball":.2,
                    "coverage":.9,
                }}
            },
            "coherence":{
                "selection_2026h1":{
                    "projected_quantile_crossing_rows":0,
                    "projected_threshold_order_violation_rows":0,
                },
                "seen_diagnostic_2026q3":{
                    "projected_quantile_crossing_rows":999,
                    "projected_threshold_order_violation_rows":999,
                },
            },
        }
        gate=research_gate(side)
        self.assertTrue(gate["coherence_gate"])
        self.assertTrue(gate["pass"])



class StressEpisodeInferenceTests(unittest.TestCase):
    def test_stress_episode_reporting_is_separate_and_explicit(self):
        anchors=[
            datetime(2026,1,1,hour=i,tzinfo=UTC)
            for i in range(8)
        ]
        bins=[2,2,2,0,0,2,2,2]
        brier=[.1,.2,.3,0,0,.4,.5,.6]
        logloss=[.2,.2,.2,0,0,.3,.3,.3]
        out=stress_episode_skill_summary(
            anchors,bins,brier,logloss,
            window_hours=1,
            minimum_duration_hours=3,
            minimum_separation_hours=4,
            stress_bin=2,
        )
        self.assertEqual(out["count"],2)
        self.assertEqual(
            out["interpretation"],
            "ROBUSTNESS_DIAGNOSTIC_NOT_STATISTICAL_INDEPENDENCE_PROOF",
        )
        self.assertGreater(out["episode_weighted_mean_brier_gain"],0)
        self.assertGreater(out["episode_weighted_mean_logloss_gain"],0)


class PublicationFaultInjectionTests(unittest.TestCase):
    def test_forecast_near_deadline_fails_before_git_publication(self):
        with tempfile.TemporaryDirectory() as td:
            old_root=worker.EVIDENCE_ROOT
            worker.EVIDENCE_ROOT=Path(td)
            try:
                with (
                    patch.object(worker,"remote_clean") as remote_clean,
                    patch.object(worker,"cmd") as git_cmd,
                ):
                    with self.assertRaises(TimeoutError):
                        worker.publish(
                            {"events":"events","branch":"evidence"},
                            {
                                "type":"FORECAST_ISSUED",
                                "idempotency_key":"forecast:20261007T000000Z",
                                "head":"1h",
                                "slot":"20261007T000000Z",
                            },
                            deadline=worker.utcnow()+timedelta(seconds=1),
                        )
                    remote_clean.assert_not_called()
                    git_cmd.assert_not_called()
            finally:
                worker.EVIDENCE_ROOT=old_root

    def test_cosign_or_rekor_signing_failure_never_commits_event(self):
        with tempfile.TemporaryDirectory() as td:
            old_root=worker.EVIDENCE_ROOT
            root=Path(td)
            worker.EVIDENCE_ROOT=root
            (root/"events").mkdir()
            try:
                with (
                    patch.object(worker,"remote_clean"),
                    patch.object(worker,"prior_events",return_value=[]),
                    patch.object(worker,"cmd") as git_cmd,
                    patch.object(
                        worker.subprocess,
                        "run",
                        side_effect=subprocess.CalledProcessError(
                            1,["cosign","sign-blob"]
                        ),
                    ),
                ):
                    with self.assertRaises(subprocess.CalledProcessError):
                        worker.publish(
                            {"events":"events","branch":"evidence"},
                            {
                                "type":"ABSTAIN_DATA_INVALID",
                                "idempotency_key":"abstain-data:20261007T000000Z",
                                "head":"1h",
                                "slot":"20261007T000000Z",
                                "reason":"FAULT_INJECTION",
                            },
                        )
                    git_cmd.assert_not_called()
            finally:
                worker.EVIDENCE_ROOT=old_root


class LivenessAndDeadlineFaultTests(unittest.TestCase):
    def test_restart_after_deadline_records_slot_missed_not_forecast(self):
        fixed_now=datetime(2026,10,7,12,16,tzinfo=UTC)
        start=fixed_now-timedelta(minutes=16)
        published=[]
        old_start=worker.START
        worker.START=start
        try:
            with (
                patch.object(worker,"utcnow",return_value=fixed_now),
                patch.object(worker,"verify_signed_freeze",return_value=[]),
                patch.object(
                    worker,
                    "publish",
                    side_effect=lambda cfg,obj,**kw: published.append(obj),
                ),
            ):
                worker.mark_missed(
                    {
                        "deadline":timedelta(minutes=14),
                        "cadence":timedelta(minutes=15),
                    },
                    "1h",
                )
            self.assertEqual(len(published),1)
            self.assertEqual(published[0]["type"],"SLOT_MISSED")
            self.assertEqual(published[0]["reason"],"NO_TIMELY_FORECAST")
        finally:
            worker.START=old_start

    def test_github_api_outage_is_fail_closed_for_liveness(self):
        with patch.object(
            chain_liveness,
            "list_runs",
            side_effect=RuntimeError("INJECTED_API_OUTAGE"),
        ):
            with self.assertRaisesRegex(
                RuntimeError,"INJECTED_API_OUTAGE"
            ):
                chain_liveness.ensure(
                    "owner/repo","workflow.yml","token"
                )


class CheckpointFaultInjectionTests(unittest.TestCase):
    def test_anchor_publication_failure_is_fail_closed(self):
        freeze={
            "type":"CONFIG_FROZEN_PRESTART",
            "manifest":{"source_commit_sha":"3"*40},
        }
        events=[({"type":"ABSTAIN_DATA_INVALID"},None) for _ in range(23)]
        events.insert(0,(freeze,None))
        with tempfile.TemporaryDirectory() as td:
            old_root=worker.EVIDENCE_ROOT
            worker.EVIDENCE_ROOT=Path(td)
            cfg={
                "checkpoint":"cp/1h.json",
                "events":"events",
                "branch":"evidence",
                "anchor_branch":"anchors",
            }
            try:
                with (
                    patch.object(worker,"prior_events",return_value=events),
                    patch.object(
                        worker,"create_signed_checkpoint",
                        return_value={
                            "verified_through_sequence":24,
                            "verified_through_event_hash":"a"*64,
                        },
                    ),
                    patch.object(
                        worker,"commit_and_push_checkpoint",
                        return_value="4"*40,
                    ),
                    patch.object(
                        worker,
                        "publish_checkpoint_anchor",
                        side_effect=RuntimeError("INJECTED_ANCHOR_FAILURE"),
                    ),
                ):
                    with self.assertRaisesRegex(
                        RuntimeError,"INJECTED_ANCHOR_FAILURE"
                    ):
                        worker.maybe_checkpoint(cfg,"1h")
            finally:
                worker.EVIDENCE_ROOT=old_root

    def test_checkpoint_remote_push_failure_is_fail_closed(self):
        freeze={
            "type":"CONFIG_FROZEN_PRESTART",
            "manifest":{"source_commit_sha":"3"*40},
        }
        events=[({"type":"ABSTAIN_DATA_INVALID"},None) for _ in range(23)]
        events.insert(0,(freeze,None))
        with tempfile.TemporaryDirectory() as td:
            old_root=worker.EVIDENCE_ROOT
            worker.EVIDENCE_ROOT=Path(td)
            cfg={
                "checkpoint":"cp/1h.json",
                "events":"events",
                "branch":"evidence",
                "anchor_branch":"anchors",
            }
            try:
                with (
                    patch.object(worker,"prior_events",return_value=events),
                    patch.object(
                        worker,"create_signed_checkpoint",
                        return_value={
                            "verified_through_sequence":24,
                            "verified_through_event_hash":"a"*64,
                        },
                    ),
                    patch.object(
                        worker,
                        "commit_and_push_checkpoint",
                        side_effect=RuntimeError("INJECTED_REMOTE_PUSH_FAILURE"),
                    ),
                ):
                    with self.assertRaisesRegex(
                        RuntimeError,"INJECTED_REMOTE_PUSH_FAILURE"
                    ):
                        worker.maybe_checkpoint(cfg,"1h")
            finally:
                worker.EVIDENCE_ROOT=old_root

    def test_anchor_recovery_failure_is_fail_closed(self):
        freeze={
            "type":"CONFIG_FROZEN_PRESTART",
            "manifest":{"source_commit_sha":"3"*40},
        }
        with tempfile.TemporaryDirectory() as td:
            old_root=worker.EVIDENCE_ROOT
            root=Path(td)
            worker.EVIDENCE_ROOT=root
            checkpoint=root/"cp/1h.json"
            checkpoint.parent.mkdir(parents=True)
            checkpoint.write_text(
                json.dumps({"verified_through_sequence":24})
            )
            cfg={
                "checkpoint":"cp/1h.json",
                "events":"events",
                "branch":"evidence",
                "anchor_branch":"anchors",
            }
            try:
                with (
                    patch.object(
                        worker,"prior_events",
                        return_value=[(freeze,None)],
                    ),
                    patch.object(
                        worker,"should_checkpoint",
                        return_value=False,
                    ),
                    patch.object(
                        worker,"_ensure_checkpoint_anchor",
                        side_effect=RuntimeError("INJECTED_RECOVERY_FAILURE"),
                    ),
                ):
                    with self.assertRaisesRegex(
                        RuntimeError,"INJECTED_RECOVERY_FAILURE"
                    ):
                        worker.maybe_checkpoint(cfg,"1h")
            finally:
                worker.EVIDENCE_ROOT=old_root


class DeploymentBundleTests(unittest.TestCase):
    def test_missing_deployment_bundle_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            with self.assertRaisesRegex(
                ValueError,"production workflow set is not exact"
            ):
                verify_deployment_bundle_against_manifest(
                    root,
                    {"workflow_commit":"0"*40},
                    {"paths_sha256":{}},
                )

    def test_safe_raw_path_rejects_traversal(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            with self.assertRaisesRegex(
                ValueError,"unsafe repository-relative path"
            ):
                safe_repo_relative_path(root,"../escape.json")

    def test_manifest_binds_all_protocols_and_workflows(self):
        root=Path(__file__).resolve().parents[1]
        old_root=worker.EVIDENCE_ROOT
        worker.EVIDENCE_ROOT=root
        try:
            with (
                patch.dict(
                    os.environ,
                    {"GITHUB_SHA": subprocess.run(
                        ["git","rev-parse","HEAD"],
                        cwd=root,check=True,capture_output=True,text=True,
                    ).stdout.strip()},
                    clear=False,
                ),
                patch.object(worker,"cmd",return_value="cosign-test"),
            ):
                manifest=worker.manifest(
                    worker.CONFIG["1h"],
                    os.environ["GITHUB_SHA"],
                )
            self.assertEqual(
                manifest["all_protocols"],list(worker.PROTOCOL_PATHS)
            )
            self.assertEqual(
                manifest["deployment_workflows"],
                list(worker.PRODUCTION_WORKFLOWS),
            )
            for p in worker.PROTOCOL_PATHS:
                self.assertIn(p,manifest["paths_sha256"])
            for p in worker.PRODUCTION_WORKFLOWS:
                self.assertIn(p,manifest["paths_sha256"])
        finally:
            worker.EVIDENCE_ROOT=old_root

    def test_deployment_bundle_rejects_one_changed_workflow(self):
        root=Path(__file__).resolve().parents[1]
        head=subprocess.run(
            ["git","rev-parse","HEAD"],
            cwd=root,check=True,capture_output=True,text=True,
        ).stdout.strip()
        old_root=worker.EVIDENCE_ROOT
        worker.EVIDENCE_ROOT=root
        try:
            with (
                patch.dict(os.environ,{"GITHUB_SHA":head},clear=False),
                patch.object(worker,"cmd",return_value="cosign-test"),
            ):
                manifest=worker.manifest(worker.CONFIG["1h"],head)
            victim=manifest["deployment_workflows"][-1]
            manifest["paths_sha256"][victim]="0"*64
            with self.assertRaises(ValueError):
                verify_deployment_bundle_against_manifest(
                    root,{"workflow_commit":head},manifest
                )
        finally:
            worker.EVIDENCE_ROOT=old_root

    def test_all_protocols_require_all_five_production_workflows(self):
        root=Path(__file__).resolve().parents[1]
        expected=list(worker.PRODUCTION_WORKFLOWS)
        self.assertEqual(len(expected),5)
        for head in ("1h","4h","24h"):
            p=json.loads(
                (root/f"predictive_vnext4r71/protocol_{head}.json").read_text()
            )
            req=p["signed_manifest_requirements"]
            self.assertEqual(
                req["all_production_workflows_required"],expected
            )
            self.assertTrue(
                p["skill_inference"]["block_confidence_intervals_required"]
            )
            self.assertTrue(
                p["skill_inference"]["separate_stress_episode_gate_required"]
            )

class WorkerIntegrationTests(unittest.TestCase):
    def test_worker_calls_checkpoint_after_complete_actions(self):
        path=Path(__file__).with_name("worker.py")
        tree=ast.parse(path.read_text())
        main=next(
            n for n in tree.body
            if isinstance(n,ast.FunctionDef) and n.name=="main"
        )
        calls=[
            n.func.id for n in ast.walk(main)
            if isinstance(n,ast.Call) and isinstance(n.func,ast.Name)
        ]
        self.assertGreaterEqual(calls.count("maybe_checkpoint"),2)
        self.assertIn("forecast",calls)
        self.assertIn("outcomes",calls)


if __name__=="__main__":
    unittest.main()
