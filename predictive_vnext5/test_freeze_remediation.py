"""Regression tests for vNext5R2 freeze evaluator remediation."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from datetime import datetime, timezone, timedelta
from pathlib import Path

import numpy as np

from predictive_vnext5 import predictor
from predictive_vnext5 import prospective_score as score
from predictive_vnext5 import verified_evidence as evidence
from predictive_vnext5 import admission_consumer as consumer
from predictive_vnext5 import prospective_admission as admission
from predictive_vnext5 import production_journal as journal


class PredictorBoundaryTests(unittest.TestCase):
    def test_inclusive_ratio_boundary(self):
        self.assertEqual(predictor.validate_sigma_domain(0.3,3.0),(0.3,3.0))
        self.assertEqual(predictor.validate_sigma_domain(0.25,2.5),(0.25,2.5))

    def test_substantive_out_of_domain_still_rejected(self):
        for pair in ((0.25,3.0),(3.0,0.25),(0.249,1.0),(3.001,1.0)):
            with self.assertRaisesRegex(ValueError,"OUT_OF_DOMAIN"):
                predictor.validate_sigma_domain(*pair)

    def test_display_rejects_negative_nan_inf_and_bad_sum(self):
        bad=(
            [1.2,-0.2,0,0],
            [float("nan"),0,0,0],
            [float("inf"),0,0,0],
            [0.2,0.2,0.2,0.2],
        )
        for raw in bad:
            with self.assertRaisesRegex(ValueError,"INVALID_RAW_PROBABILITY"):
                predictor.display_three_state(raw)

    def test_display_basis_vectors(self):
        expected=((1,0,0),(0,0,1),(0,1,0),(.5,0,.5))
        for k,want in enumerate(expected):
            got=predictor.display_three_state(np.eye(4)[k])
            self.assertEqual(
                tuple(got[x] for x in ("DOWN","RANGE","UP")),want
            )


class EvaluationSemanticsTests(unittest.TestCase):
    def setUp(self):
        self.start=datetime(2026,10,12,tzinfo=timezone.utc)

    def row(self, *, head="1h", candidate="1h", anchor=None):
        anchor=anchor or self.start
        hours={"1h":1,"4h":4,"24h":24}[head]
        deadline={"1h":1,"4h":1,"24h":1}[head]
        due=anchor+timedelta(hours=hours)
        return {
            "schema":"btc-predictive-vnext5r2-canonical-row-v1",
            "query_type":"CANONICAL",
            "target_id":"CANONICAL_SIGMA_1_1_V1",
            "lower_sigma":1.0,
            "upper_sigma":1.0,
            "head":head,
            "candidate_id":candidate,
            "anchor_utc":anchor.isoformat(),
            "forecast_issued_at_utc":(
                anchor+timedelta(minutes=deadline)
            ).isoformat(),
            "due_utc":due.isoformat(),
            "outcome_recorded_at_utc":due.isoformat(),
            "prediction_raw":[1.0,0.0,0.0,0.0],
            "outcome_class":0,
            "volatility":0.002,
        }

    def test_ece10_exact(self):
        p=np.asarray([[.8,.1,.1,0],[.6,.2,.2,0],[.4,.3,.3,0]],float)
        y=np.asarray([0,1,0])
        got=score.ece10(p,y)
        self.assertAlmostEqual(got,1.4/3)

    def test_weekly_block_ci_is_seeded(self):
        anchors=[
            datetime(2026,1,1,tzinfo=timezone.utc)+timedelta(days=i*7)
            for i in range(8)
        ]
        gain=np.linspace(.01,.08,8)
        a=score.block_ci_gain(gain,anchors,200,20261008)
        b=score.block_ci_gain(gain,anchors,200,20261008)
        self.assertEqual(a,b)
        self.assertGreater(a[0],0)

    def test_anchor_grid_24h(self):
        cutoff=self.start+timedelta(days=3)
        grid=score.expected_anchor_grid("24h",self.start,cutoff)
        self.assertEqual(len(grid),3)

    def test_baseline_is_due_causal(self):
        runtime={"volatility_bin_edges":[.01,.02],
                 "frozen_prior_counts_by_bin":{"0":[10,10,10,1],
                                                "1":[10,10,10,1],
                                                "2":[10,10,10,1]},
                 "frozen_global_prior_counts":[30,30,30,3]}
        rows=[]
        for i in range(35):
            a=self.start+timedelta(hours=i)
            rows.append({
                "_anchor":a,
                "_due":a+timedelta(hours=1),
                "_y":0 if i<34 else 1,
                "_vol":.005,
            })
        p=score.baseline_probabilities(rows,runtime)
        frozen=score.smoothed([10,10,10,1],.5)
        np.testing.assert_allclose(p[1],frozen,rtol=0,atol=1e-15)

    def test_pre_anchor_forecast_rejected(self):
        row=self.row()
        row["forecast_issued_at_utc"]=(self.start-timedelta(seconds=1)).isoformat()
        with self.assertRaisesRegex(ValueError,"before anchor"):
            score.validate_rows([row],"1h",self.start,self.start+timedelta(hours=1))

    def test_fractional_and_bool_outcome_rejected(self):
        for bad in (0.5,True,False,1.0):
            row=self.row()
            row["outcome_class"]=bad
            with self.assertRaisesRegex(ValueError,"strict integer"):
                score.validate_rows([row],"1h",self.start,self.start+timedelta(hours=1))

    def test_custom_zone_row_rejected(self):
        row=self.row()
        row["query_type"]="CUSTOM_ZONE"
        row["lower_sigma"]=0.5
        row["upper_sigma"]=2.0
        with self.assertRaisesRegex(ValueError,"custom/non-canonical"):
            score.validate_rows([row],"1h",self.start,self.start+timedelta(hours=1))

    def test_unknown_custom_annotation_rejected(self):
        row=self.row()
        row["free_form_custom_zone"]=True
        with self.assertRaisesRegex(ValueError,"unexpected canonical row fields"):
            score.validate_rows([row],"1h",self.start,self.start+timedelta(hours=1))

    def test_post_cutoff_outcome_rejected(self):
        row=self.row()
        cutoff=self.start+timedelta(hours=1)
        row["outcome_recorded_at_utc"]=(cutoff+timedelta(seconds=1)).isoformat()
        with self.assertRaisesRegex(ValueError,"after evaluation cutoff"):
            score.validate_rows([row],"1h",self.start,cutoff)

    def test_valid_canonical_row_accepted(self):
        row=self.row()
        by,grid=score.validate_rows(
            [row],"1h",self.start,self.start+timedelta(hours=1)
        )
        self.assertEqual(len(grid),1)
        self.assertIn(("1h",self.start),by)


    def test_exact_deadline_is_rejected_consistently(self):
        row=self.row()
        row["forecast_issued_at_utc"]=(self.start+timedelta(minutes=14)).isoformat()
        with self.assertRaisesRegex(ValueError,"late forecast"):
            score.validate_rows([row],"1h",self.start,self.start+timedelta(hours=1))

    def test_signed_event_extra_custom_fields_rejected_before_derivation(self):
        base={
            "schema":"btc-predictive-vnext5r42-evidence-event-v1",
            "sequence":3,
            "previous_hash":"0"*64,
            "workflow_commit":"1"*40,
            "published_at_utc":self.start.isoformat(),
            "type":"FORECAST_ISSUED",
            "idempotency_key":"forecast:test",
            "head":"1h",
            "trading_authority":False,
            "slot":"test",
            "anchor_utc":self.start.isoformat(),
            "due_utc":(self.start+timedelta(hours=1)).isoformat(),
            "query_type":"CANONICAL",
            "target_id":"CANONICAL_SIGMA_1_1_V1",
            "lower_sigma":1.0,
            "upper_sigma":1.0,
            "predictions":{"1h":[.25,.25,.5,0.0]},
            "artifact_sha256":{"1h":"a"*64},
            "volatility":.002,
            "reference_price":80000.0,
            "lower_price":79000.0,
            "upper_price":81000.0,
            "feature_sha256":"b"*64,
            "raw_path":"predictive_vnext5_1h_raw/test.json",
            "raw_sha256":"c"*64,
            "producer_mode":"PRODUCTION",
        }
        evidence._validate_exact_event_schema(base)
        for key,value in (
            ("custom_zone",[82000,87000]),
            ("actual_query_type","CUSTOM_ZONE"),
            ("free_form_note","anything"),
        ):
            attack=dict(base);attack[key]=value
            with self.assertRaisesRegex(ValueError,"forbidden fields"):
                evidence._validate_exact_event_schema(attack)

    def test_full_4h_grid_extra_fields_rejected_before_derivation(self):
        start=datetime(2026,10,12,tzinfo=timezone.utc)
        rejected=0
        for i in range(252):
            a=start+timedelta(hours=4*i)
            event={
                "schema":"btc-predictive-vnext5r42-evidence-event-v1",
                "sequence":3,
                "previous_hash":"0"*64,
                "workflow_commit":"1"*40,
                "published_at_utc":a.isoformat(),
                "type":"FORECAST_ISSUED",
                "idempotency_key":"forecast:"+a.isoformat(),
                "head":"4h",
                "trading_authority":False,
                "slot":a.strftime("%Y%m%dT%H%M%SZ"),
                "anchor_utc":a.isoformat(),
                "due_utc":(a+timedelta(hours=4)).isoformat(),
                "query_type":"CANONICAL",
                "target_id":"CANONICAL_SIGMA_1_1_V1",
                "lower_sigma":1.0,
                "upper_sigma":1.0,
                "predictions":{"4h":[.25,.25,.5,0.0]},
                "artifact_sha256":{"4h":"a"*64},
                "volatility":.002,
                "reference_price":83000.0,
                "lower_price":82500.0,
                "upper_price":83500.0,
                "feature_sha256":"b"*64,
                "raw_path":"predictive_vnext5_4h_raw/test.json",
                "raw_sha256":"c"*64,
                "producer_mode":"PRODUCTION",
                "custom_zone":[82000.0,87000.0],
                "actual_query_type":"CUSTOM_ZONE",
            }
            with self.assertRaisesRegex(ValueError,"forbidden fields"):
                evidence._validate_exact_event_schema(event)
            rejected+=1
        self.assertEqual(rejected,252)

    def test_modified_runtime_rejected(self):
        runtime=score.authoritative_runtime()
        changed=copy.deepcopy(runtime)
        changed["heads"]["1h"]["volatility_bin_edges"]=[10.0,20.0]
        with self.assertRaisesRegex(ValueError,"non-authoritative runtime"):
            score.authoritative_runtime(changed)


class ConsumerBoundaryTests(unittest.TestCase):
    def decision(self):
        tip="a"*40
        source="b"*40
        return {
            "schema":"btc-predictive-vnext5r42-verified-admission-v1",
            "head":"4h",
            "cutoff_utc":"2026-12-01T00:00:00+00:00",
            "admission_ready":True,
            "selected_candidate":"4h",
            "prospective_skill_proven":False,
            "trading_authority":False,
            "governance":{
                "full_cryptographic_replay":True,
                "all_event_signatures_verified":True,
                "all_rekor_inclusion_proofs_verified":True,
                "event_hash_chain_verified":True,
                "workflow_content_binding_verified":True,
                "static_source_manifest_verified":True,
                "execution_contract_verified":True,
                "executed_source_bytes_verified":True,
                "raw_hashes_verified":True,
                "raw_remote_publication_verified":True,
                "forecast_delivery_receipt_verified":True,
                "canonical_rows_derived_only_from_verified_journal":True,
                "standalone_jsonl_admission_forbidden":True,
                "remote_tip_revalidated_after_scoring":True,
                "numerical_provenance_replayed":True,
                "trusted_source_bootstrap_verified":True,
                "outcome_barriers_bound_to_forecast":True,
                "protocol_mode":"PROSPECTIVE",
                "admission_eligible":True,
                "evidence_branch":"test-evidence",
                "evidence_tip":tip,
                "verified_source_commit_sha":source,
                "trusted_approved_source_sha":source,
            },
        }

    def test_consumer_has_no_arbitrary_decision_api(self):
        self.assertFalse(hasattr(consumer,"assert_current_snapshot"))
        with self.assertRaises(TypeError):
            consumer.consume_verified_admission(decision={"admission_ready":True})

    def test_consumer_runs_authoritative_admission_then_rechecks_tip(self):
        d=self.decision()
        with patch.object(consumer,"run_verified_admission",return_value=d), \
             patch.object(consumer,"_remote_tip",return_value="a"*40):
            got=consumer.consume_verified_admission(
                repo_root=".",
                approved_source_sha="b"*40,
                head="4h",
                evidence_branch="test-evidence",
                protocol_path="protocol.json",
                cutoff_utc="2026-12-01T00:00:00Z",
                model_root="/tmp/models",
            )
        self.assertTrue(got["snapshot_current"])
        self.assertTrue(got["admission_ready"])
        self.assertFalse(got["trading_authority"])

    def test_consumer_rejects_stale_tip_after_authoritative_admission(self):
        d=self.decision()
        with patch.object(consumer,"run_verified_admission",return_value=d), \
             patch.object(consumer,"_remote_tip",return_value="c"*40):
            with self.assertRaisesRegex(ValueError,"stale"):
                consumer.consume_verified_admission(
                    repo_root=".",
                    approved_source_sha="b"*40,
                    head="4h",
                    evidence_branch="test-evidence",
                    protocol_path="protocol.json",
                    cutoff_utc="2026-12-01T00:00:00Z",
                    model_root="/tmp/models",
                )

    def test_consumer_rejects_forged_trust_claim(self):
        d=self.decision()
        d["governance"]["trusted_source_bootstrap_verified"]=False
        with patch.object(consumer,"run_verified_admission",return_value=d):
            with self.assertRaisesRegex(ValueError,"trusted_source_bootstrap_verified"):
                consumer.consume_verified_admission(
                    repo_root=".",
                    approved_source_sha="b"*40,
                    head="4h",
                    evidence_branch="test-evidence",
                    protocol_path="protocol.json",
                    cutoff_utc="2026-12-01T00:00:00Z",
                    model_root="/tmp/models",
                )

    def test_production_signer_drift_rejected_before_publication(self):
        verified=SimpleNamespace(
            source_commit_sha="d"*40,
            governance={
                "source_ref":"refs/heads/frozen",
                "workflow_trigger":"workflow_dispatch",
            },
        )
        good={
            "GITHUB_SHA":"d"*40,
            "GITHUB_REF":"refs/heads/frozen",
            "GITHUB_EVENT_NAME":"workflow_dispatch",
        }
        with patch.dict("os.environ",good,clear=False):
            journal._assert_current_signer_matches_registration(verified)
        bad={**good,"GITHUB_REF":"refs/heads/wrong"}
        with patch.dict("os.environ",bad,clear=False):
            with self.assertRaisesRegex(RuntimeError,"ref"):
                journal._assert_current_signer_matches_registration(verified)


class FreezeBindingTests(unittest.TestCase):
    def root(self):
        return Path(__file__).resolve().parents[1]

    def test_binary_pinned_manifest_matches_parent_hashes(self):
        root=self.root()
        build=root/"predictive_vnext5/build"
        manifest=json.loads((build/"freeze_manifest.json").read_text())
        contract=json.loads(
            (root/"predictive_vnext5/reproducibility_contract.json").read_text()
        )
        parent=contract["model_authority"]["parent"]["inner_sha256"]
        self.assertEqual(
            manifest["model_authority"]["mode"],
            "INHERITED_IMMUTABLE_PARENT_BINARY",
        )
        self.assertFalse(manifest["model_authority"]["retraining_performed"])
        for name,row in manifest["artifacts"].items():
            actual=hashlib.sha256((build/name).read_bytes()).hexdigest()
            self.assertEqual(actual,parent[name])
            self.assertEqual(row["sha256"],parent[name])

    def test_protocol_binds_sole_verified_admission_entrypoint(self):
        root=self.root()
        p=json.loads(
            (root/"predictive_vnext5/prospective_protocol.json").read_text()
        )
        b=p["evaluation_binding"]
        self.assertEqual(
            b["sole_admission_entrypoint"],
            "predictive_vnext5/prospective_admission.py",
        )
        self.assertEqual(
            b["evidence_verifier_path"],
            "predictive_vnext5/verified_evidence.py",
        )
        self.assertEqual(
            b["calculator_path"],
            "predictive_vnext5/prospective_score.py",
        )
        self.assertTrue(b["arbitrary_jsonl_admission_forbidden"])
        self.assertTrue(b["changes_after_start_forbidden"])
        self.assertTrue(b["runtime_override_forbidden"])
        self.assertTrue(b["strict_canonical_schema_required"])
        self.assertEqual(
            b["consumer_guard_path"],
            "predictive_vnext5/admission_consumer.py",
        )
        self.assertTrue(b["consumer_exact_tip_recheck_required"])
        self.assertTrue(b["production_writer_serialization_required"])
        self.assertTrue(b["production_signer_identity_recheck_before_publish"])
        self.assertFalse(b["journal_source_selects_executable_code"])
        self.assertTrue(b["consumer_calls_authoritative_admission_directly"])
        self.assertFalse(b["arbitrary_decision_object_consumer_input"])
        self.assertTrue(b["outcome_event_barrier_equality_required"])
        self.assertTrue(b["full_signature_rekor_replay_required"])
        self.assertTrue(b["raw_remote_publication_required"])
        self.assertTrue(b["delivery_receipt_binding_required"])
        self.assertEqual(b["row_time_authority"],"REKOR_INTEGRATED_TIME")
        self.assertEqual(b["primary_query_type"],"CANONICAL")
        self.assertEqual(b["primary_target_id"],"CANONICAL_SIGMA_1_1_V1")

    def test_manifest_hash_bindings_are_live(self):
        root=self.root()
        build=root/"predictive_vnext5/build"
        m=json.loads((build/"freeze_manifest.json").read_text())
        expected={
            "evaluation_runtime_sha256":build/"evaluation_runtime.json",
            "evaluation_supplement_sha256":
                root/"predictive_vnext5/evaluation_supplement.json",
            "prospective_protocol_sha256":
                root/"predictive_vnext5/prospective_protocol.json",
            "prospective_scorer_sha256":
                root/"predictive_vnext5/prospective_score.py",
            "prospective_admission_sha256":
                root/"predictive_vnext5/prospective_admission.py",
            "admission_worker_sha256":
                root/"predictive_vnext5/admission_worker.py",
            "admission_consumer_sha256":
                root/"predictive_vnext5/admission_consumer.py",
            "verified_evidence_sha256":
                root/"predictive_vnext5/verified_evidence.py",
            "evidence_protocol_template_sha256":
                root/"predictive_vnext5/evidence_protocol_template.json",
            "execution_contract_sha256":
                root/"predictive_vnext5/execution_contract.json",
            "production_emitter_sha256":
                root/"predictive_vnext5/production_emitter.py",
            "production_journal_sha256":
                root/"predictive_vnext5/production_journal.py",
            "market_replay_e2e_sha256":
                root/"predictive_vnext5/market_replay_e2e.py",
            "signed_semantic_negative_e2e_sha256":
                root/"predictive_vnext5/signed_semantic_negative_e2e.py",
            "signed_outcome_negative_e2e_sha256":
                root/"predictive_vnext5/signed_outcome_negative_e2e.py",
            "trust_bootstrap_regression_sha256":
                root/"predictive_vnext5/trust_bootstrap_regression.py",
            "frozen_source_runtime_sha256":
                root/"predictive_vnext5/frozen_evaluation_runtime.json",
            "evidence_workflow_sha256":
                root/".github/workflows/btc-predictive-vnext5r42-evidence.yml",
        }
        for key,path in expected.items():
            self.assertEqual(
                m[key],hashlib.sha256(path.read_bytes()).hexdigest()
            )
        score.authoritative_runtime()

    def test_packaged_runtime_is_exact_source_runtime(self):
        root=self.root()
        source=(root/"predictive_vnext5/frozen_evaluation_runtime.json").read_bytes()
        packaged=(root/"predictive_vnext5/build/evaluation_runtime.json").read_bytes()
        self.assertEqual(source,packaged)


    def test_execution_contract_requires_complete_runtime_and_producer_graph(self):
        root=self.root()
        contract=json.loads(
            (root/"predictive_vnext5/execution_contract.json").read_text()
        )
        required=set(contract["required_source_paths"])
        must={
            "predictive_vnext5/verified_evidence.py",
            "predictive_vnext5/prospective_admission.py",
            "predictive_vnext5/admission_worker.py",
            "predictive_vnext5/prospective_score.py",
            "predictive_vnext5/production_emitter.py",
            "predictive_vnext5/production_journal.py",
            "predictive_vnext5/admission_consumer.py",
            "predictive_vnext5/signed_semantic_negative_e2e.py",
            "predictive_vnext5/signed_outcome_negative_e2e.py",
            "predictive_vnext5/trust_bootstrap_regression.py",
            "predictive_vnext5/frozen_evaluation_runtime.json",
            "predictive_vnext4r6/live_features.py",
            "predictive_vnext4/core.py",
            "predictive_vnext4r71/crypto.py",
            "predictive_vnext4r7/integrity.py",
            ".github/workflows/btc-predictive-vnext5r42-evidence.yml",
        }
        self.assertTrue(must.issubset(required))

    def test_evidence_template_preserves_model_authority(self):
        root=self.root()
        t=json.loads(
            (root/"predictive_vnext5/evidence_protocol_template.json").read_text()
        )
        contract=json.loads(
            (root/"predictive_vnext5/reproducibility_contract.json").read_text()
        )
        parent=contract["model_authority"]["parent"]["inner_sha256"]
        self.assertEqual(
            t["heads"]["1h"]["artifact_sha256"]["1h"],
            parent["head_1h_classifier.joblib"],
        )
        self.assertEqual(
            t["heads"]["4h"]["artifact_sha256"]["4h"],
            parent["head_4h_classifier.joblib"],
        )
        self.assertEqual(
            t["heads"]["24h"]["artifact_sha256"]["24h_classifier"],
            parent["head_24h_classifier.joblib"],
        )
        self.assertEqual(
            t["heads"]["24h"]["artifact_sha256"]["24h_competing_risks"],
            parent["head_24h_competing_risks.joblib"],
        )


if __name__=="__main__":
    unittest.main()
