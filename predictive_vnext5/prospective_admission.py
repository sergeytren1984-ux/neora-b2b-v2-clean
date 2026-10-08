"""Sole prospective admission entrypoint for vNext5R3 first-passage.

Input authority is an exact fetched remote evidence branch.  Arbitrary JSONL
forecast/outcome rows are not accepted.  The function verifies an immutable
snapshot cryptographically, derives canonical rows from signed events, then
invokes the frozen numerical scorer.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from predictive_vnext5.verified_evidence import verify_evidence_snapshot
from predictive_vnext5.prospective_score import score


def _git(root:Path,*args,text=True):
    return subprocess.run(
        ["git","-C",str(root),*args],
        check=True,capture_output=True,text=text,timeout=180
    ).stdout


def _fetch_remote_tip(root:Path,branch:str)->str:
    if not isinstance(branch,str) or not branch:
        raise ValueError("evidence branch missing")
    subprocess.run(
        ["git","-C",str(root),"fetch","origin",branch],
        check=True,capture_output=True,timeout=180
    )
    return _git(root,"rev-parse","origin/"+branch).strip()


def _snapshot(root:Path,tip:str)->Path:
    parent=Path(tempfile.mkdtemp(prefix="vnext5-admission-"))
    snap=parent/"worktree"
    try:
        subprocess.run(
            ["git","-C",str(root),"worktree","add","--detach",str(snap),tip],
            check=True,capture_output=True,timeout=180
        )
    except Exception:
        shutil.rmtree(parent,ignore_errors=True)
        raise
    return snap


def _remove_snapshot(root:Path,snap:Path):
    subprocess.run(
        ["git","-C",str(root),"worktree","remove","--force",str(snap)],
        check=False,capture_output=True,timeout=180
    )
    shutil.rmtree(snap.parent,ignore_errors=True)


def run_verified_admission(
    *,
    repo_root:str,
    head:str,
    evidence_branch:str,
    protocol_path:str,
    cutoff_utc:str,
    allow_e2e_short_horizon:bool=False,
):
    if head not in {"1h","4h","24h"}:
        raise ValueError("invalid head")
    root=Path(repo_root).resolve()
    initial_tip=_fetch_remote_tip(root,evidence_branch)
    snap=_snapshot(root,initial_tip)
    try:
        protocol_file=snap/protocol_path
        protocol=json.loads(protocol_file.read_text())
        if protocol.get("head")!=head:
            raise ValueError("protocol/head mismatch")
        events_dir=protocol.get("events_dir")
        if not isinstance(events_dir,str) or not events_dir:
            raise ValueError("protocol events_dir missing")

        verified=verify_evidence_snapshot(
            root=snap,
            protocol_path=protocol_path,
            events_dir=events_dir,
            current_tip=initial_tip,
            expected_branch=evidence_branch,
            allow_e2e_short_horizon=allow_e2e_short_horizon,
        )
        runtime=json.loads(
            (snap/"predictive_vnext5/frozen_evaluation_runtime.json").read_text()
        )
        decision=score(
            list(verified.rows),
            head,
            verified.start_utc,
            cutoff_utc,
            runtime,
        )

        observed=_fetch_remote_tip(root,evidence_branch)
        if observed!=initial_tip:
            raise ValueError("remote evidence tip changed during admission")

        decision["schema"]="btc-predictive-vnext5r3-verified-admission-v1"
        decision["governance"]={
            **verified.governance,
            "private_detached_snapshot":True,
            "remote_tip_revalidated_after_scoring":True,
            "decision_semantics":"SNAPSHOT_AS_OF_EXACT_EVIDENCE_SHA",
            "evidence_branch":verified.evidence_branch,
            "evidence_tip":verified.evidence_tip,
            "verified_source_commit_sha":verified.source_commit_sha,
            "canonical_rows_derived_only_from_verified_journal":True,
            "standalone_jsonl_admission_forbidden":True,
        }
        decision["prospective_skill_proven"]=False
        decision["trading_authority"]=False
        return decision
    finally:
        _remove_snapshot(root,snap)


def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument("--head",required=True,choices=("1h","4h","24h"))
    p.add_argument("--evidence-branch",required=True)
    p.add_argument("--protocol-path",required=True)
    p.add_argument("--cutoff-utc",required=True)
    p.add_argument("--repo-root",default=".")
    args=p.parse_args(argv)
    result=run_verified_admission(
        repo_root=args.repo_root,
        head=args.head,
        evidence_branch=args.evidence_branch,
        protocol_path=args.protocol_path,
        cutoff_utc=args.cutoff_utc,
    )
    print(json.dumps(result,indent=2,sort_keys=True))


if __name__=="__main__":
    main()
