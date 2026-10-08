"""Sole prospective admission launcher for vNext5R4.2.

Trust bootstrap rule: no source SHA read from evidence may select executable
code.  The caller must provide an approved source SHA from deployment/freeze
configuration outside the evidence journal.  This launcher must itself execute
from that exact approved commit.  Only then is the trusted admission worker
loaded from a detached checkout of the same approved commit and allowed to
authenticate the journal.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HEX40=re.compile(r"^[0-9a-f]{40}$")
LAUNCHER_ROOT=Path(__file__).resolve().parents[1]


def _git(root:Path,*args):
    return subprocess.run(
        ["git","-C",str(root),*args],
        check=True,capture_output=True,text=True,timeout=180
    ).stdout.strip()


def _fetch_remote_tip(root:Path,branch:str)->str:
    subprocess.run(
        ["git","-C",str(root),"fetch","origin",branch],
        check=True,capture_output=True,timeout=180
    )
    return _git(root,"rev-parse","origin/"+branch)


def _worktree(root:Path,commit:str,prefix:str)->Path:
    parent=Path(tempfile.mkdtemp(prefix=prefix))
    path=parent/"worktree"
    try:
        subprocess.run(
            ["git","-C",str(root),"worktree","add","--detach",str(path),commit],
            check=True,capture_output=True,timeout=180
        )
    except Exception:
        shutil.rmtree(parent,ignore_errors=True)
        raise
    return path


def _remove(root:Path,path:Path):
    subprocess.run(
        ["git","-C",str(root),"worktree","remove","--force",str(path)],
        check=False,capture_output=True,timeout=180
    )
    shutil.rmtree(path.parent,ignore_errors=True)


def _trusted_approved_source(repo_root:Path,approved_source_sha:str)->str:
    approved=str(approved_source_sha).lower()
    if not HEX40.fullmatch(approved):
        raise ValueError("approved source SHA must be an exact 40-hex commit")

    launcher_head=_git(LAUNCHER_ROOT,"rev-parse","HEAD")
    if launcher_head!=approved:
        raise ValueError(
            "launcher checkout is not the externally approved source commit"
        )

    # Ensure the approved object exists in the repository used for worktrees,
    # but never derive approval from evidence content.
    resolved=_git(repo_root,"rev-parse",approved+"^{commit}")
    if resolved!=approved:
        raise ValueError("approved source SHA does not resolve exactly")
    return approved


def run_verified_admission(
    *,
    repo_root:str,
    approved_source_sha:str,
    head:str,
    evidence_branch:str,
    protocol_path:str,
    cutoff_utc:str,
    model_root:str,
    allow_e2e_short_horizon:bool=False,
):
    root=Path(repo_root).resolve()
    approved=_trusted_approved_source(root,approved_source_sha)

    # Evidence is snapshotted independently.  No event is parsed to choose code.
    tip=_fetch_remote_tip(root,evidence_branch)
    evidence=_worktree(root,tip,"vnext5r42-evidence-")
    source=_worktree(root,approved,"vnext5r42-approved-source-")
    try:
        code=(
            "import sys;"
            f"sys.path.insert(0,{str(source)!r});"
            "from predictive_vnext5.admission_worker import main;"
            "main(sys.argv[1:])"
        )
        argv=[
            sys.executable,"-I","-c",code,
            "--repo-root",str(root),
            "--source-root",str(source),
            "--approved-source-sha",approved,
            "--evidence-root",str(evidence),
            "--evidence-tip",tip,
            "--evidence-branch",evidence_branch,
            "--protocol-path",protocol_path,
            "--head",head,
            "--cutoff-utc",cutoff_utc,
            "--model-root",str(Path(model_root).resolve()),
        ]
        if allow_e2e_short_horizon:
            argv.append("--allow-e2e-short-horizon")
        proc=subprocess.run(
            argv,check=True,capture_output=True,text=True,timeout=900
        )
        decision=json.loads(proc.stdout)
        governance=decision.get("governance",{})
        if governance.get("trusted_approved_source_sha")!=approved:
            raise ValueError("worker decision lacks trusted approved source binding")
        return decision
    finally:
        _remove(root,source)
        _remove(root,evidence)


def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument("--approved-source-sha",required=True)
    p.add_argument("--head",required=True,choices=("1h","4h","24h"))
    p.add_argument("--evidence-branch",required=True)
    p.add_argument("--protocol-path",required=True)
    p.add_argument("--cutoff-utc",required=True)
    p.add_argument("--model-root",required=True)
    p.add_argument("--repo-root",default=".")
    args=p.parse_args(argv)
    result=run_verified_admission(
        repo_root=args.repo_root,
        approved_source_sha=args.approved_source_sha,
        head=args.head,
        evidence_branch=args.evidence_branch,
        protocol_path=args.protocol_path,
        cutoff_utc=args.cutoff_utc,
        model_root=args.model_root,
    )
    print(json.dumps(result,indent=2,sort_keys=True))


if __name__=="__main__":
    main()
