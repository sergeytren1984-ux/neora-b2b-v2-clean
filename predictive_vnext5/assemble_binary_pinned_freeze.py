"""Assemble remediated vNext5R3 provenance-bound freeze from exact parent model binaries.

No training occurs here. The four numerical model binaries are inherited
byte-for-byte from the parent freeze artifact and verified against frozen SHA256
values before packaging. Only evaluation/runtime metadata and boundary code are
new in R1.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import shutil
from pathlib import Path

import joblib
import numpy as np
import scipy
import sklearn
import threadpoolctl

from predictive_vnext4.core import (
    read_klines, build_15m_features, build_hourly_features,
)
from predictive_vnext5 import predictor
from research_vnext5 import predictive_research as r1

ROOT=Path(__file__).resolve().parents[1]
HERE=ROOT/"predictive_vnext5"
BUILD=HERE/"build"
SPEC=json.loads((HERE/"freeze_spec.json").read_text())
REPRO=json.loads((HERE/"reproducibility_contract.json").read_text())
EVAL=json.loads((HERE/"evaluation_supplement.json").read_text())
CANONICAL_PID=SPEC["target_contract"]["training_barrier_sigma_pairs"].index([1.0,1.0])


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def locate(root,name):
    hits=list(Path(root).rglob(name))
    if len(hits)!=1:
        raise RuntimeError(f"expected one {name} under {root}, got {hits}")
    return hits[0]


def assert_environment():
    if platform.system()!=REPRO["platform"]["system"]:
        raise RuntimeError("platform system mismatch")
    if platform.machine()!=REPRO["platform"]["machine"]:
        raise RuntimeError("platform machine mismatch")
    if platform.python_version()!=REPRO["python"]:
        raise RuntimeError("python version mismatch")
    actual={
        "numpy":np.__version__,
        "scipy":scipy.__version__,
        "scikit_learn":sklearn.__version__,
        "joblib":joblib.__version__,
        "threadpoolctl":threadpoolctl.__version__,
    }
    if actual!=REPRO["packages"]:
        raise RuntimeError(f"package mismatch: {actual}")
    for k,v in REPRO["environment"].items():
        if os.environ.get(k)!=v:
            raise RuntimeError(f"environment mismatch {k}")
    pools=threadpoolctl.threadpool_info()
    bad=[
        p for p in pools
        if p.get("user_api") in ("blas","openmp")
        and int(p.get("num_threads",0))!=1
    ]
    if bad:
        raise RuntimeError(f"threadpool not single-threaded: {bad}")
    stable=[]
    for p in pools:
        stable.append({
            k:p.get(k) for k in (
                "user_api","internal_api","prefix","version",
                "num_threads","threading_layer"
            )
        })
    stable.sort(key=lambda x:json.dumps(x,sort_keys=True))
    return {
        "schema":"btc-predictive-vnext5r3-build-environment-v4",
        "platform":REPRO["platform"],
        "python":platform.python_version(),
        "packages":actual,
        "environment":REPRO["environment"],
        "threadpools":stable,
        "model_training_performed":False,
    }


def final_masks(dates,due,head):
    cutoff=np.datetime64("2026-07-01T00:00:00")
    end=np.datetime64(
        "2026-10-01T00:00:00" if head in ("1h","4h")
        else "2026-09-25T00:00:00"
    )
    due_dates=dates+due
    train=due_dates<cutoff
    cal=(dates>=cutoff)&(due_dates<end)
    return train,cal


def runtime_head(head,vol,pair_id,y,train):
    mask=np.asarray(train,dtype=bool)&(
        np.asarray(pair_id,dtype=int)==CANONICAL_PID
    )
    vv=np.asarray(vol,dtype=float)[mask]
    yy=np.asarray(y,dtype=int)[mask]
    if len(vv)<100:
        raise RuntimeError("insufficient frozen baseline rows")
    edges=np.quantile(vv,[1/3,2/3],method="linear")
    bins=np.digitize(vv,edges,right=True)
    return {
        "head":head,
        "volatility_bin_edges":[float(x) for x in edges],
        "volatility_bin_method":"numpy.quantile method=linear at [1/3,2/3]",
        "frozen_prior_counts_by_bin":{
            str(i):np.bincount(yy[bins==i],minlength=4).astype(int).tolist()
            for i in range(3)
        },
        "frozen_global_prior_counts":
            np.bincount(yy,minlength=4).astype(int).tolist(),
        "canonical_training_n":int(len(yy)),
        "raw_class_order":EVAL["raw_class_order"],
        "baseline_name":EVAL["baseline"]["name"],
    }


def build_evaluation_runtime():
    path=ROOT/"research_vnext4r6/data/BTCUSDT_15m_2024-01_2026-09.json.gz"
    t,o,hi,lo,c,v,trades,taker,sha15=read_klines(path,900000)
    ix,dates,X,names,regime,vol=build_15m_features(
        t,hi,lo,c,v,trades,taker,16
    )
    heads={}
    for head,bars in (("1h",4),("4h",16)):
        due=np.timedelta64(bars*15,"m")
        ZX,zy,zd,zr,zv,zpid,_=r1.zone_augmented_dataset(
            X,dates,regime,vol,ix,c,hi,lo,bars,due
        )
        train,_=final_masks(zd,due,head)
        heads[head]=runtime_head(head,zv,zpid,zy,train)

    path=ROOT/"btc_1h_2024_to_sep24_2026.json"
    t,o,hi,lo,c,v,trades,taker,sha1=read_klines(path,3600000)
    ix,dates,X,names,regime,vol,atr=build_hourly_features(
        t,hi,lo,c,v,trades,taker,24
    )
    due=np.timedelta64(24,"h")
    ZX,zy,zd,zr,zv,zpid,_=r1.zone_augmented_dataset(
        X,dates,regime,vol,ix,c,hi,lo,24,due
    )
    train,_=final_masks(zd,due,"24h")
    heads["24h"]=runtime_head("24h",zv,zpid,zy,train)
    return {
        "schema":"btc-predictive-vnext5r2-evaluation-runtime-v3",
        "supplement_sha256":sha(HERE/"evaluation_supplement.json"),
        "source_sha256":{"15m":sha15,"1h":sha1},
        "heads":heads,
        "immutable_after_start":True,
    }


def _fingerprint_float(value):
    # Diagnostic fingerprint only.  Independent runners with the exact same
    # model bytes differed by at most ~5.6e-17 from floating-point execution.
    # Quantize only the audit fingerprint, never model inference.
    return round(float(value),15)


def behavior_fingerprint():
    vec=json.loads((BUILD/"selftest_vectors.json").read_text())
    bundles={
        "1h":joblib.load(BUILD/"head_1h_classifier.joblib"),
        "4h":joblib.load(BUILD/"head_4h_classifier.joblib"),
        "24h_classifier":joblib.load(BUILD/"head_24h_classifier.joblib"),
        "24h_competing_risks":joblib.load(BUILD/"head_24h_competing_risks.joblib"),
    }
    pairs=((1.0,1.0),(0.5,2.0),(0.3,3.0))
    result={}
    for name,bundle in bundles.items():
        head="24h" if name.startswith("24h") else name
        base=vec[head]["base_features"]
        func=(
            predictor.hazard_raw_probability
            if name=="24h_competing_risks"
            else predictor.classifier_raw_probability
        )
        result[name]={}
        for lo,up in pairs:
            raw=func(bundle,base,lo,up)
            result[name][f"{lo:g}_{up:g}"]={
                "raw":[_fingerprint_float(x) for x in raw],
                "display":{
                    k:_fingerprint_float(v)
                    for k,v in predictor.display_three_state(raw).items()
                },
            }
    return {
        "schema":"btc-predictive-vnext5r1-model-behavior-fingerprint-v1",
        "pairs":[list(x) for x in pairs],
        "round_decimal_places":15,
        "raw_inference_is_not_quantized":True,
        "models":result,
    }


def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument("--parent-dir",required=True)
    args=p.parse_args(argv)
    env=assert_environment()
    parent=Path(args.parent_dir)
    expected=REPRO["model_authority"]["parent"]["inner_sha256"]

    BUILD.mkdir(parents=True,exist_ok=True)
    for old in BUILD.iterdir():
        if old.is_file():
            old.unlink()
        elif old.is_dir():
            shutil.rmtree(old)

    model_names=[
        "head_1h_classifier.joblib","head_4h_classifier.joblib",
        "head_24h_classifier.joblib","head_24h_competing_risks.joblib",
        "selftest_vectors.json",
    ]
    for name in model_names:
        src=locate(parent,name)
        if sha(src)!=expected[name]:
            raise RuntimeError(f"parent artifact SHA mismatch: {name}")
        shutil.copyfile(src,BUILD/name)

    parent_manifest=locate(parent,"freeze_manifest.json")
    if sha(parent_manifest)!=expected["freeze_manifest.json"]:
        raise RuntimeError("parent freeze manifest SHA mismatch")
    shutil.copyfile(parent_manifest,BUILD/"parent_freeze_manifest.json")

    source_runtime=HERE/"frozen_evaluation_runtime.json"
    if not source_runtime.exists():
        raise RuntimeError("frozen source evaluation runtime missing")
    shutil.copyfile(source_runtime,BUILD/"evaluation_runtime.json")
    (BUILD/"build_environment.json").write_text(
        json.dumps(env,indent=2,sort_keys=True)+"\n"
    )
    fingerprint=behavior_fingerprint()
    (BUILD/"model_behavior_fingerprint.json").write_text(
        json.dumps(fingerprint,indent=2,sort_keys=True)+"\n"
    )

    artifact_hashes={
        name:sha(BUILD/name) for name in model_names if name.endswith(".joblib")
    }
    if artifact_hashes!={
        k:v for k,v in expected.items() if k.endswith(".joblib")
    }:
        raise RuntimeError("copied model binaries changed")

    manifest={
        "schema":"btc-predictive-vnext5r3-provenance-bound-freeze-manifest-v4",
        "status":"PROVENANCE_BOUND_PRESTART_BINARY_PINNED_PACKAGE",
        "model_authority":{
            "mode":"INHERITED_IMMUTABLE_PARENT_BINARY",
            "parent_source_sha":
                REPRO["model_authority"]["parent"]["source_sha"],
            "parent_workflow_run_id":
                REPRO["model_authority"]["parent"]["workflow_run_id"],
            "parent_artifact_id":
                REPRO["model_authority"]["parent"]["artifact_id"],
            "parent_artifact_zip_digest":
                REPRO["model_authority"]["parent"]["artifact_zip_digest"],
            "retraining_performed":False,
        },
        "artifacts":{
            name:{
                "path":"predictive_vnext5/build/"+name,
                "sha256":sha(BUILD/name),
            }
            for name in model_names if name.endswith(".joblib")
        },
        "parent_freeze_manifest_sha256":
            sha(BUILD/"parent_freeze_manifest.json"),
        "selftest_vectors_sha256":sha(BUILD/"selftest_vectors.json"),
        "evaluation_runtime_sha256":sha(BUILD/"evaluation_runtime.json"),
        "build_environment_sha256":sha(BUILD/"build_environment.json"),
        "model_behavior_fingerprint_sha256":
            sha(BUILD/"model_behavior_fingerprint.json"),
        "freeze_spec_sha256":sha(HERE/"freeze_spec.json"),
        "prospective_protocol_sha256":sha(HERE/"prospective_protocol.json"),
        "reproducibility_contract_sha256":
            sha(HERE/"reproducibility_contract.json"),
        "evaluation_supplement_sha256":
            sha(HERE/"evaluation_supplement.json"),
        "prospective_scorer_sha256":sha(HERE/"prospective_score.py"),
        "prospective_admission_sha256":sha(HERE/"prospective_admission.py"),
        "verified_evidence_sha256":sha(HERE/"verified_evidence.py"),
        "evidence_protocol_template_sha256":
            sha(HERE/"evidence_protocol_template.json"),
        "frozen_source_runtime_sha256":
            sha(HERE/"frozen_evaluation_runtime.json"),
        "f4_adversarial_regression_sha256":
            sha(HERE/"f4_adversarial_regression.py"),
        "provenance_e2e_sha256":sha(HERE/"provenance_e2e.py"),
        "evidence_workflow_sha256":
            sha(ROOT/".github/workflows/btc-predictive-vnext5r3-evidence.yml"),
        "predictor_sha256":sha(HERE/"predictor.py"),
        "evaluation_authority":{
            "sole_admission_entrypoint":
                "predictive_vnext5/prospective_admission.py",
            "evidence_verifier":
                "predictive_vnext5/verified_evidence.py",
            "calculator_only":
                "predictive_vnext5/prospective_score.py",
            "arbitrary_jsonl_admission":False,
            "runtime_override_allowed":False,
            "runtime_source_controlled":True,
            "primary_query_type":"CANONICAL",
            "primary_target_id":"CANONICAL_SIGMA_1_1_V1",
            "strict_row_schema":True,
            "as_of_cutoff_semantics":True,
            "rekor_time_authority":True,
            "exact_remote_tip_snapshot_required":True,
        },
        "historical_model_selection_change":False,
        "predictive_model_change":False,
        "start_utc":None,
        "prospective_skill_proven":False,
        "trading_authority":False,
        "post_assembly_reproducibility_verification":
            "TWIN_RUNNER_EXACT_BYTE_COMPARE_REQUIRED",
    }
    (BUILD/"freeze_manifest.json").write_text(
        json.dumps(manifest,indent=2,sort_keys=True)+"\n"
    )
    print(json.dumps(manifest,indent=2,sort_keys=True))


if __name__=="__main__":
    main()
