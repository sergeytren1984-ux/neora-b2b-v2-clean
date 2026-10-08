"""Immutable-source admission worker for vNext5R4.1.

This module must execute from a detached checkout whose HEAD equals the signed
source_commit_sha.  It performs cryptographic evidence replay, numerical
provenance replay, frozen scoring, and the post-score remote-tip check.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
from pathlib import Path

import joblib
import numpy as np
import scipy
import sklearn
import threadpoolctl

from predictive_vnext5.verified_evidence import verify_evidence_snapshot
from predictive_vnext5.prospective_score import score


def _git(root:Path,*args):
    return subprocess.run(
        ["git","-C",str(root),*args],
        check=True,capture_output=True,text=True,timeout=180
    ).stdout.strip()


def _remote_tip(repo_root:Path,branch:str)->str:
    subprocess.run(
        ["git","-C",str(repo_root),"fetch","origin",branch],
        check=True,capture_output=True,timeout=180
    )
    return _git(repo_root,"rev-parse","origin/"+branch)


def _assert_runtime_contract(source_root:Path):
    contract=json.loads(
        (source_root/"predictive_vnext5/execution_contract.json").read_text()
    )
    runtime=contract["runtime"]
    if platform.python_version()!=runtime["python"]:
        raise ValueError("executed Python version differs from frozen contract")
    actual={
        "numpy":np.__version__,
        "scipy":scipy.__version__,
        "scikit_learn":sklearn.__version__,
        "joblib":joblib.__version__,
        "threadpoolctl":threadpoolctl.__version__,
    }
    if actual!=runtime["packages"]:
        raise ValueError("executed package versions differ from frozen contract")
    for key,value in runtime["env"].items():
        if os.environ.get(key)!=value:
            raise ValueError("executed environment differs from frozen contract: "+key)
    bad=[
        p for p in threadpoolctl.threadpool_info()
        if p.get("user_api") in ("blas","openmp")
        and int(p.get("num_threads",0))!=1
    ]
    if bad:
        raise ValueError("executed numerical threadpool differs from frozen contract")
    return contract


def run_worker(
    *,
    repo_root:str,
    source_root:str,
    evidence_root:str,
    evidence_tip:str,
    evidence_branch:str,
    protocol_path:str,
    head:str,
    cutoff_utc:str,
    model_root:str,
    allow_e2e_short_horizon:bool=False,
):
    repo=Path(repo_root).resolve()
    source=Path(source_root).resolve()
    evidence=Path(evidence_root).resolve()
    models=Path(model_root).resolve()

    source_head=_git(source,"rev-parse","HEAD")
    if source_head!=_git(source,"rev-parse","HEAD^{commit}"):
        raise ValueError("source checkout is not an exact commit")
    contract=_assert_runtime_contract(source)

    protocol=json.loads((evidence/protocol_path).read_text())
    events_dir=protocol.get("events_dir")
    if not isinstance(events_dir,str) or not events_dir:
        raise ValueError("protocol events_dir missing")

    verified=verify_evidence_snapshot(
        root=evidence,
        protocol_path=protocol_path,
        events_dir=events_dir,
        current_tip=evidence_tip,
        expected_branch=evidence_branch,
        allow_e2e_short_horizon=allow_e2e_short_horizon,
        source_checkout=source,
        model_root=models,
        require_numerical_replay=not allow_e2e_short_horizon,
    )
    if verified.source_commit_sha!=source_head:
        raise ValueError("executed source checkout differs from signed source")

    runtime=json.loads(
        (source/"predictive_vnext5/frozen_evaluation_runtime.json").read_text()
    )
    decision=score(
        list(verified.rows),
        head,
        verified.start_utc,
        cutoff_utc,
        runtime,
    )

    observed=_remote_tip(repo,evidence_branch)
    if observed!=evidence_tip:
        raise ValueError("remote evidence tip changed during admission")

    decision["schema"]="btc-predictive-vnext5r41-verified-admission-v1"
    decision["governance"]={
        **verified.governance,
        "executed_source_checkout":source_head,
        "execution_contract_schema":contract["schema"],
        "private_detached_evidence_snapshot":True,
        "private_detached_source_snapshot":True,
        "remote_tip_revalidated_after_scoring":True,
        "decision_semantics":"SNAPSHOT_AS_OF_EXACT_EVIDENCE_SHA",
        "evidence_branch":verified.evidence_branch,
        "evidence_tip":verified.evidence_tip,
        "verified_source_commit_sha":verified.source_commit_sha,
        "canonical_rows_derived_only_from_verified_journal":True,
        "standalone_jsonl_admission_forbidden":True,
        "numerical_provenance_replayed":not allow_e2e_short_horizon,
    }
    decision["prospective_skill_proven"]=False
    decision["trading_authority"]=False
    return decision


def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument("--repo-root",required=True)
    p.add_argument("--source-root",required=True)
    p.add_argument("--evidence-root",required=True)
    p.add_argument("--evidence-tip",required=True)
    p.add_argument("--evidence-branch",required=True)
    p.add_argument("--protocol-path",required=True)
    p.add_argument("--head",required=True,choices=("1h","4h","24h"))
    p.add_argument("--cutoff-utc",required=True)
    p.add_argument("--model-root",required=True)
    p.add_argument("--allow-e2e-short-horizon",action="store_true")
    args=p.parse_args(argv)
    out=run_worker(
        repo_root=args.repo_root,
        source_root=args.source_root,
        evidence_root=args.evidence_root,
        evidence_tip=args.evidence_tip,
        evidence_branch=args.evidence_branch,
        protocol_path=args.protocol_path,
        head=args.head,
        cutoff_utc=args.cutoff_utc,
        model_root=args.model_root,
        allow_e2e_short_horizon=args.allow_e2e_short_horizon,
    )
    print(json.dumps(out,indent=2,sort_keys=True))


if __name__=="__main__":
    main()
