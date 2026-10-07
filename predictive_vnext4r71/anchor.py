"""Independent signed checkpoint anchor for R7.1.

The checkpoint is first committed to the evidence branch. A second signed document
then records that remote checkpoint commit and is published to a separate anchor
branch. Both documents are independently logged by Rekor.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from predictive_vnext4r7.integrity import canonical, digest

UTC=timezone.utc


def _run(root:Path,*args,check=True,text=True):
    return subprocess.run(
        ["git","-C",str(root),*args],
        check=check,capture_output=True,text=text,timeout=180
    )


def _git(root:Path,*args)->str:
    return _run(root,*args).stdout.strip()


def _remote_branch_sha(root:Path,branch:str)->str|None:
    out=_git(root,"ls-remote","origin","refs/heads/"+branch)
    return out.split()[0] if out else None


def _git_bytes(root:Path,commit:str,path:str)->bytes:
    return _run(root,"show",f"{commit}:{path}",text=False).stdout


def publish_checkpoint_anchor(
    *,
    repo_root:Path,
    anchor_branch:str,
    base_commit:str,
    evidence_branch:str,
    head:str,
    checkpoint_path:Path,
    checkpoint_bundle_path:Path,
    checkpoint_doc:dict,
    checkpoint_remote_commit:str,
    workflow_commit:str,
    sign_blob,
    require_bundle_time,
    verify_blob=None,
)->dict:
    rel_checkpoint=str(checkpoint_path.resolve().relative_to(repo_root.resolve()))
    rel_bundle=str(checkpoint_bundle_path.resolve().relative_to(repo_root.resolve()))
    cp_bytes=_git_bytes(repo_root,checkpoint_remote_commit,rel_checkpoint)
    bundle_bytes=_git_bytes(repo_root,checkpoint_remote_commit,rel_bundle)
    if cp_bytes!=checkpoint_path.read_bytes():
        raise ValueError("remote checkpoint commit lacks exact checkpoint")
    if bundle_bytes!=checkpoint_bundle_path.read_bytes():
        raise ValueError("remote checkpoint commit lacks exact checkpoint bundle")

    with tempfile.TemporaryDirectory(prefix="r71-anchor-") as td:
        work=Path(td)/"work"
        remote_before=_remote_branch_sha(repo_root,anchor_branch)
        if remote_before:
            _git(repo_root,"fetch","origin",anchor_branch)
            subprocess.run(
                ["git","-C",str(repo_root),"worktree","add","--detach",str(work),"origin/"+anchor_branch],
                check=True,capture_output=True,text=True,timeout=180
            )
        else:
            subprocess.run(
                ["git","-C",str(repo_root),"worktree","add","--detach",str(work),base_commit],
                check=True,capture_output=True,text=True,timeout=180
            )
        try:
            anchor_dir=work/"predictive_vnext4r71_checkpoint_anchors"/head
            anchor_dir.mkdir(parents=True,exist_ok=True)
            existing=sorted(
                p for p in anchor_dir.glob("*.json")
                if len(p.stem)==8 and p.stem.isdigit()
            )
            previous_hash=None
            prev_cp_seq=int(checkpoint_doc.get("previous_checkpoint_sequence",0))
            prev_cp_sha=checkpoint_doc.get("previous_checkpoint_sha256")
            if existing:
                previous_raw=existing[-1].read_bytes()
                previous_doc=json.loads(previous_raw)
                previous_hash=digest(previous_raw)
                if int(previous_doc.get("verified_through_sequence",-1))!=prev_cp_seq:
                    raise ValueError("checkpoint predecessor does not match latest anchor")
                if previous_doc.get("checkpoint_sha256")!=prev_cp_sha:
                    raise ValueError("checkpoint predecessor hash does not match latest anchor")
            elif prev_cp_seq!=0 or prev_cp_sha is not None:
                raise ValueError("prior anchor chain missing for non-first checkpoint")

            seq=int(checkpoint_doc["verified_through_sequence"])
            path=anchor_dir/f"{seq:08d}.json"
            if path.exists():
                existing=json.loads(path.read_bytes())
                stable={
                    "head":head,
                    "evidence_branch":evidence_branch,
                    "anchor_branch":anchor_branch,
                    "verified_through_sequence":seq,
                    "verified_through_event_hash":checkpoint_doc["verified_through_event_hash"],
                    "checkpoint_sha256":digest(checkpoint_path.read_bytes()),
                    "checkpoint_bundle_sha256":digest(checkpoint_bundle_path.read_bytes()),
                    "checkpoint_path":rel_checkpoint,
                    "checkpoint_bundle_path":rel_bundle,
                    "checkpoint_remote_commit":checkpoint_remote_commit,
                    "verified_branch_commit":checkpoint_doc["verified_branch_commit"],
                    "previous_checkpoint_sequence":prev_cp_seq,
                    "previous_checkpoint_sha256":prev_cp_sha,
                    "manifest_sha256":checkpoint_doc["manifest_sha256"],
                    "source_commit_sha":checkpoint_doc["source_commit_sha"],
                    "workflow_commit":workflow_commit,
                }
                for key,value in stable.items():
                    if existing.get(key)!=value:
                        raise ValueError("existing anchor conflicts: "+key)
                bundle=path.with_suffix(".sigstore.json")
                if not bundle.exists():
                    raise ValueError("existing anchor bundle missing")
                if verify_blob is not None:
                    verify_blob(path,bundle,existing)
                return {
                    "document":existing,
                    "anchor_path":str(path.relative_to(work)),
                    "anchor_bundle_path":str(bundle.relative_to(work)),
                    "anchor_remote_commit":remote_before,
                    "rekor_time_utc":require_bundle_time(bundle).isoformat(),
                    "recovered_existing":True,
                }
            doc={
                "schema":"btc-predictive-vnext4r71-checkpoint-anchor-v1",
                "head":head,
                "evidence_branch":evidence_branch,
                "anchor_branch":anchor_branch,
                "verified_through_sequence":seq,
                "verified_through_event_hash":checkpoint_doc["verified_through_event_hash"],
                "checkpoint_sha256":digest(checkpoint_path.read_bytes()),
                "checkpoint_bundle_sha256":digest(checkpoint_bundle_path.read_bytes()),
                "checkpoint_path":rel_checkpoint,
                "checkpoint_bundle_path":rel_bundle,
                "checkpoint_remote_commit":checkpoint_remote_commit,
                "verified_branch_commit":checkpoint_doc["verified_branch_commit"],
                "previous_checkpoint_sequence":prev_cp_seq,
                "previous_checkpoint_sha256":prev_cp_sha,
                "manifest_sha256":checkpoint_doc["manifest_sha256"],
                "source_commit_sha":checkpoint_doc["source_commit_sha"],
                "workflow_commit":workflow_commit,
                "previous_anchor_hash":previous_hash,
                "created_at_utc":datetime.now(UTC).isoformat(),
                "trading_authority":False,
            }
            path.write_bytes(canonical(doc))
            bundle=path.with_suffix(".sigstore.json")
            sign_blob(path,bundle)
            require_bundle_time(bundle)

            _git(work,"config","user.name","btc-predictive-r71-anchor[bot]")
            _git(work,"config","user.email","btc-predictive-r71-anchor[bot]@users.noreply.github.com")
            _git(work,"add",str(path.relative_to(work)),str(bundle.relative_to(work)))
            _git(work,"commit","-m",f"BTC predictive R7.1 {head} checkpoint anchor {seq}")
            parent=_git(work,"rev-parse","HEAD^")
            if remote_before and parent!=remote_before:
                raise RuntimeError("anchor branch lost single-writer tip")
            _git(work,"push","origin","HEAD:"+anchor_branch)
            remote_after=_remote_branch_sha(work,anchor_branch)
            local=_git(work,"rev-parse","HEAD")
            if remote_after!=local:
                raise RuntimeError("anchor remote publication unconfirmed")
            return {
                "document":doc,
                "anchor_path":str(path.relative_to(work)),
                "anchor_bundle_path":str(bundle.relative_to(work)),
                "anchor_remote_commit":local,
                "rekor_time_utc":require_bundle_time(bundle).isoformat(),
            }
        finally:
            subprocess.run(
                ["git","-C",str(repo_root),"worktree","remove",str(work),"--force"],
                check=False,capture_output=True,text=True,timeout=180
            )


def verify_latest_anchor(
    *,
    repo_root:Path,
    anchor_branch:str,
    head:str,
    manifest:dict,
    workflow_path:str,
    current_evidence_tip:str,
    verify_blob,
    verify_workflow_binding,
)->dict:
    """Verify the complete signed anchor chain and return its latest anchor."""
    _git(repo_root,"fetch","origin",anchor_branch)
    ref="origin/"+anchor_branch
    base=f"predictive_vnext4r71_checkpoint_anchors/{head}"
    listing=_git(repo_root,"ls-tree","-r","--name-only",ref,"--",base)
    json_paths=sorted(
        p for p in listing.splitlines()
        if p.startswith(base+"/") and p.endswith(".json")
        and not p.endswith(".sigstore.json")
    )
    if not json_paths:
        raise ValueError("required checkpoint anchor missing")

    previous_raw=None
    previous_doc=None
    latest=None
    latest_path=None
    for path in json_paths:
        bundle_path=path[:-5]+".sigstore.json"
        raw=_git_bytes(repo_root,ref,path)
        bundle_raw=_git_bytes(repo_root,ref,bundle_path)
        with tempfile.TemporaryDirectory(prefix="r71-anchor-verify-") as td:
            p=Path(td)/"anchor.json"
            b=Path(td)/"anchor.sigstore.json"
            p.write_bytes(raw); b.write_bytes(bundle_raw)
            doc=json.loads(raw)
            if raw!=canonical(doc):
                raise ValueError("anchor not canonical")
            if doc.get("head")!=head or doc.get("anchor_branch")!=anchor_branch:
                raise ValueError("anchor identity mismatch")
            expected_previous=(
                None if previous_raw is None else digest(previous_raw)
            )
            if doc.get("previous_anchor_hash")!=expected_previous:
                raise ValueError("anchor hash chain broken")
            expected_prev_seq=(
                0 if previous_doc is None
                else int(previous_doc["verified_through_sequence"])
            )
            expected_prev_cp_sha=(
                None if previous_doc is None
                else previous_doc["checkpoint_sha256"]
            )
            if int(doc.get("previous_checkpoint_sequence",-1))!=expected_prev_seq:
                raise ValueError("anchor checkpoint predecessor sequence broken")
            if doc.get("previous_checkpoint_sha256")!=expected_prev_cp_sha:
                raise ValueError("anchor checkpoint predecessor hash broken")
            verify_blob(p,b,doc)
            verify_workflow_binding(repo_root,doc,workflow_path,manifest)

        cp_commit=doc.get("checkpoint_remote_commit")
        if not isinstance(cp_commit,str) or len(cp_commit)!=40:
            raise ValueError("anchor checkpoint commit invalid")
        subprocess.run(
            ["git","-C",str(repo_root),"merge-base","--is-ancestor",cp_commit,current_evidence_tip],
            check=True,capture_output=True,timeout=180
        )
        cp=_git_bytes(repo_root,cp_commit,doc["checkpoint_path"])
        cb=_git_bytes(repo_root,cp_commit,doc["checkpoint_bundle_path"])
        if digest(cp)!=doc["checkpoint_sha256"]:
            raise ValueError("anchored checkpoint hash mismatch")
        if digest(cb)!=doc["checkpoint_bundle_sha256"]:
            raise ValueError("anchored checkpoint bundle hash mismatch")
        previous_raw=raw
        previous_doc=doc
        latest=doc
        latest_path=path

    return {
        "verified":True,
        "anchor_count":len(json_paths),
        "verified_through_sequence":int(latest["verified_through_sequence"]),
        "checkpoint_remote_commit":latest["checkpoint_remote_commit"],
        "anchor_remote_ref":ref,
        "anchor_path":latest_path,
        "full_anchor_chain_verified":True,
    }

