"""Sole prospective admission launcher for vNext5R4.

The launcher itself performs no scoring and imports no evaluator/model modules.
It fetches an exact evidence tip, discovers the claimed source SHA, creates two
detached worktrees, and executes admission_worker.py from the claimed source
checkout under Python isolated mode.  The worker cryptographically verifies that
the claimed source SHA is the signed source authority before any decision can
return.
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


def _claimed_source(evidence_root:Path,protocol_path:str)->str:
    protocol=json.loads((evidence_root/protocol_path).read_text())
    events_dir=protocol.get("events_dir")
    if not isinstance(events_dir,str):
        raise ValueError("protocol events_dir missing")
    event_path=evidence_root/events_dir/"00000001.json"
    event=json.loads(event_path.read_text())
    source=str(event.get("source_commit_sha","")).lower()
    if not HEX40.fullmatch(source):
        raise ValueError("schedule does not claim a valid source commit")
    return source


def run_verified_admission(
    *,
    repo_root:str,
    head:str,
    evidence_branch:str,
    protocol_path:str,
    cutoff_utc:str,
    model_root:str,
    allow_e2e_short_horizon:bool=False,
):
    root=Path(repo_root).resolve()
    tip=_fetch_remote_tip(root,evidence_branch)
    evidence=_worktree(root,tip,"vnext5r4-evidence-")
    source=None
    try:
        source_sha=_claimed_source(evidence,protocol_path)
        source=_worktree(root,source_sha,"vnext5r4-source-")
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
        return json.loads(proc.stdout)
    finally:
        if source is not None:
            _remove(root,source)
        _remove(root,evidence)


def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument("--head",required=True,choices=("1h","4h","24h"))
    p.add_argument("--evidence-branch",required=True)
    p.add_argument("--protocol-path",required=True)
    p.add_argument("--cutoff-utc",required=True)
    p.add_argument("--model-root",required=True)
    p.add_argument("--repo-root",default=".")
    args=p.parse_args(argv)
    result=run_verified_admission(
        repo_root=args.repo_root,
        head=args.head,
        evidence_branch=args.evidence_branch,
        protocol_path=args.protocol_path,
        cutoff_utc=args.cutoff_utc,
        model_root=args.model_root,
    )
    print(json.dumps(result,indent=2,sort_keys=True))


if __name__=="__main__":
    main()
