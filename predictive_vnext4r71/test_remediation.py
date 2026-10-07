"""Adversarial regression tests for the R7.1 blockers found by independent audit."""
from __future__ import annotations

import ast
import inspect
import json
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from predictive_vnext4r7.integrity import canonical, digest
from predictive_vnext4r7.scorecard_core import score_from_events
from predictive_vnext4r71.admission import run_admission
from predictive_vnext4r71.checkpoint import git_prefix_binding
from predictive_vnext4r71.integrity import validate_event_collection
from predictive_vnext4r71.tail_research import (
    monotone_exceedance,
    monotone_quantiles,
    quantile_crossings,
    threshold_order_violations,
)

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

    def test_public_admission_has_no_verifier_override(self):
        params=inspect.signature(run_admission).parameters
        self.assertNotIn("verify_forecast_blob",params)
        self.assertNotIn("verify_outcome_blob",params)

    def test_disabled_signed_protocol_blocks_before_scoring(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            p=root/"protocol.json"
            p.write_text(json.dumps({"admission_enabled":False,"head":"1h"}))
            out=run_admission(
                repo_root=str(root),
                protocol_path="protocol.json",
                events_dir="events",
                forecast_workflow=".github/workflows/f.yml",
                outcome_workflow=".github/workflows/f.yml",
                head="1h",
                start_utc=datetime(2026,10,7,tzinfo=UTC),
                horizon=timedelta(hours=1),
                issuance_deadline=timedelta(minutes=14),
                repository="owner/repo",
            )
            self.assertFalse(out["admission_ready"])
            self.assertEqual(out["status"],"BLOCKED_PROTOCOL_ADMISSION_DISABLED")


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
