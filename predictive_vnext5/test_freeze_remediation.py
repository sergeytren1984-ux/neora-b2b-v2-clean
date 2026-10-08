"""Regression tests for vNext5R1 freeze audit findings F2-F4."""
from __future__ import annotations
import hashlib
import json
import math
import unittest
from pathlib import Path
from datetime import datetime, timezone, timedelta

import numpy as np

from predictive_vnext5 import predictor
from predictive_vnext5 import prospective_score as score


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
    def test_ece10_exact(self):
        p=np.asarray([[.8,.1,.1,0],[.6,.2,.2,0],[.4,.3,.3,0]],float)
        y=np.asarray([0,1,0])
        got=score.ece10(p,y)
        self.assertTrue(math.isfinite(got))
        self.assertGreaterEqual(got,0)

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
        start=datetime(2026,10,9,tzinfo=timezone.utc)
        cutoff=start+timedelta(days=3)
        grid=score.expected_anchor_grid("24h",start,cutoff)
        self.assertEqual(len(grid),3)
        self.assertEqual(grid[0],start)
        self.assertEqual(grid[1],start+timedelta(days=1))
        self.assertEqual(grid[2],start+timedelta(days=2))

    def test_baseline_is_due_causal(self):
        runtime={"volatility_bin_edges":[.01,.02],
                 "frozen_prior_counts_by_bin":{"0":[10,10,10,1],
                                                "1":[10,10,10,1],
                                                "2":[10,10,10,1]},
                 "frozen_global_prior_counts":[30,30,30,3]}
        base=datetime(2026,1,1,tzinfo=timezone.utc)
        rows=[]
        for i in range(35):
            a=base+timedelta(hours=i)
            rows.append({
                "_anchor":a,
                "_due":a+timedelta(hours=1),
                "_y":0 if i<34 else 1,
                "_vol":.005,
            })
        p=score.baseline_probabilities(rows,runtime)
        # Row 1 cannot use row 0 because its due equals current anchor and rule is strict.
        frozen=score.smoothed([10,10,10,1],.5)
        np.testing.assert_allclose(p[1],frozen,rtol=0,atol=1e-15)



class FreezeBindingTests(unittest.TestCase):
    def test_binary_pinned_manifest_matches_parent_hashes(self):
        root=Path(__file__).resolve().parents[1]
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

    def test_protocol_binds_one_executable_scorer(self):
        root=Path(__file__).resolve().parents[1]
        p=json.loads(
            (root/"predictive_vnext5/prospective_protocol.json").read_text()
        )
        binding=p["evaluation_binding"]
        self.assertTrue(binding["scorer_is_only_admission_implementation"])
        self.assertTrue(binding["changes_after_start_forbidden"])
        self.assertEqual(
            binding["scorer_path"],
            "predictive_vnext5/prospective_score.py",
        )
        self.assertEqual(
            binding["supplement_path"],
            "predictive_vnext5/evaluation_supplement.json",
        )


if __name__=="__main__":
    unittest.main()
