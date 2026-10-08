"""Production signed journal worker for vNext5R4.

Actions:
- register: create signed pre-start protocol/schedule/freeze for one head;
- forecast: emit one frozen-phase forecast from fresh closed market candles;
- outcome: resolve due forecasts from forward market candles.

This file is frozen before START.  It never trains or changes the numerical
model.  All numerical values are produced by production_emitter.py and are
independently recomputed by verified_evidence.py during admission.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from predictive_vnext4r7.integrity import canonical, digest
from predictive_vnext4r71.crypto import bundle_time
from predictive_vnext5.production_emitter import (
    MODEL_FILES, HEADS, fetch_forecast_raw, fetch_outcome_raw,
    nearest_closed_anchor, recompute_outcome_from_raw,
)
from predictive_vnext5.verified_evidence import verify_evidence_snapshot

UTC=timezone.utc
ROOT=Path(__file__).resolve().parents[1]
REPO="sergeytren1984-ux/neora-b2b-v2-clean"
WORKFLOW=".github/workflows/btc-predictive-vnext5r4-evidence.yml"


def cmd(root:Path,*args,check=True):
    return subprocess.run(
        ["git","-C",str(root),*args],
        check=check,capture_output=True,text=True,timeout=300
    ).stdout.strip()


def sign(root:Path,path:Path,bundle:Path):
    subprocess.run(
        ["cosign","sign-blob","--yes","--bundle",str(bundle),str(path)],
        cwd=root,check=True,capture_output=True,text=True,timeout=180
    )


def source_hash(source_sha,path):
    raw=subprocess.run(
        ["git","-C",str(ROOT),"show",f"{source_sha}:{path}"],
        check=True,capture_output=True,timeout=120
    ).stdout
    return digest(raw)


def _create_or_open_evidence_worktree(branch,source_sha):
    subprocess.run(
        ["git","-C",str(ROOT),"fetch","origin"],
        check=True,capture_output=True,timeout=180
    )
    parent=Path(tempfile.mkdtemp(prefix="vnext5r4-production-evidence-"))
    path=parent/"worktree"
    exists=subprocess.run(
        ["git","-C",str(ROOT),"show-ref","--verify","--quiet","refs/remotes/origin/"+branch],
        check=False,capture_output=True,
    ).returncode==0
    if exists:
        commit=cmd(ROOT,"rev-parse","origin/"+branch)
        subprocess.run(
            ["git","-C",str(ROOT),"worktree","add","--detach",str(path),commit],
            check=True,capture_output=True,timeout=180
        )
        cmd(path,"checkout","-B",branch,commit)
    else:
        subprocess.run(
            ["git","-C",str(ROOT),"worktree","add","-b",branch,str(path),source_sha],
            check=True,capture_output=True,timeout=180
        )
        cmd(path,"push","-u","origin","HEAD:"+branch)
    cmd(path,"config","user.name","btc-vnext5r4-production[bot]")
    cmd(path,"config","user.email","btc-vnext5r4-production[bot]@users.noreply.github.com")
    return path


def _remove_worktree(path):
    subprocess.run(
        ["git","-C",str(ROOT),"worktree","remove","--force",str(path)],
        check=False,capture_output=True,text=True,timeout=180
    )
    shutil.rmtree(path.parent,ignore_errors=True)


def _remote_tip(branch):
    cmd(ROOT,"fetch","origin",branch)
    return cmd(ROOT,"rev-parse","origin/"+branch)


def _event_files(events_dir):
    return sorted(
        p for p in events_dir.glob("*.json")
        if len(p.stem)==8 and p.stem.isdigit()
    )


def _events(events_dir):
    return [json.loads(p.read_bytes()) for p in _event_files(events_dir)]


def _make_event(events_dir,obj):
    prior=_events(events_dir)
    return {
        "schema":"btc-predictive-vnext5r4-evidence-event-v1",
        "sequence":len(prior)+1,
        "previous_hash":digest(canonical(prior[-1])) if prior else None,
        "workflow_commit":os.environ["GITHUB_SHA"],
        "published_at_utc":datetime.now(UTC).isoformat(),
        **obj,
    }


def _publish(root,branch,events_dir,event,attachments=(),deadline=None):
    path=events_dir/f"{event['sequence']:08d}.json"
    bundle=path.with_suffix(".sigstore.json")
    path.write_bytes(canonical(event))
    sign(root,path,bundle)
    integrated=bundle_time(bundle)
    if deadline is not None and integrated>=deadline:
        path.unlink(missing_ok=True); bundle.unlink(missing_ok=True)
        raise TimeoutError("event Rekor time reached/exceeded frozen deadline")

    for item in (path,bundle,*attachments):
        rel=str(Path(item).resolve().relative_to(root.resolve()))
        cmd(root,"add",rel)
    cmd(root,"commit","-m",f"vNext5R4 {event['head']} #{event['sequence']} {event['type']}")
    cmd(root,"push","origin","HEAD:"+branch)
    local=cmd(root,"rev-parse","HEAD")
    remote=cmd(root,"ls-remote","origin","refs/heads/"+branch).split()[0]
    if local!=remote:
        raise RuntimeError("remote production publication mismatch")
    return local,integrated


def _phase_valid(head,start):
    s=start.astimezone(UTC)
    if s.minute or s.second or s.microsecond:
        return False
    if head=="1h":
        return True
    if head=="4h":
        return s.hour%4==0
    if head=="24h":
        return s.hour==0
    return False


def _protocol(head,template,events_dir):
    return {
        "schema":"btc-predictive-vnext5r4-production-protocol-v1",
        "mode":"PROSPECTIVE",
        "head":head,
        "events_dir":events_dir,
        "repository":REPO,
        "workflow_path":WORKFLOW,
        "canonical_target":template["canonical_target"],
        "head_config":template["heads"][head],
        "trading_authority":False,
    }


def _manifest(head,branch,protocol_bytes,source_sha,source_ref,trigger,template):
    execution=json.loads(
        (ROOT/"predictive_vnext5/execution_contract.json").read_text()
    )
    paths={}
    for path in execution["required_source_paths"]:
        paths[path]=source_hash(source_sha,path)
    artifact={
        c:MODEL_FILES[c][1]
        for c in template["heads"][head]["candidates"]
    }
    return {
        "schema":"btc-predictive-vnext5r4-production-manifest-v1",
        "source_commit_sha":source_sha,
        "source_ref":source_ref,
        "workflow_trigger":trigger,
        "evidence_branch":branch,
        "protocol_sha256":digest(protocol_bytes),
        "model_artifact_sha256":artifact,
        "paths_sha256":paths,
        "execution_contract_sha256":
            paths["predictive_vnext5/execution_contract.json"],
        "producer_mode":"PRODUCTION",
        "trading_authority":False,
    }


def _verify_branch(root,head,branch,protocol_rel,model_root):
    tip=_remote_tip(branch)
    if cmd(root,"rev-parse","HEAD")!=tip:
        raise RuntimeError("local evidence worktree is not exact remote tip")
    verified=verify_evidence_snapshot(
        root=root,
        protocol_path=protocol_rel,
        events_dir=json.loads((root/protocol_rel).read_text())["events_dir"],
        current_tip=tip,
        expected_branch=branch,
        source_checkout=ROOT,
        model_root=model_root,
        require_numerical_replay=True,
    )
    return verified


def register(head,branch,start,model_root):
    if os.environ.get("GITHUB_EVENT_NAME")!="workflow_dispatch":
        raise RuntimeError("production registration requires workflow_dispatch")
    if not _phase_valid(head,start):
        raise ValueError("START_UTC is not on frozen head phase")
    if start<=datetime.now(UTC)+timedelta(minutes=10):
        raise ValueError("START_UTC must leave pre-start signing margin")

    source_sha=os.environ["GITHUB_SHA"]
    source_ref=os.environ["GITHUB_REF"]
    trigger=os.environ["GITHUB_EVENT_NAME"]
    root=_create_or_open_evidence_worktree(branch,source_sha)
    try:
        template=json.loads(
            (ROOT/"predictive_vnext5/evidence_protocol_template.json").read_text()
        )
        events_rel=template["journal"]["events_dir_template"].format(head=head)
        protocol_rel=f"predictive_vnext5_evidence/{head}/protocol.json"
        events_dir=root/events_rel
        events_dir.mkdir(parents=True,exist_ok=True)
        protocol_path=root/protocol_rel
        if _event_files(events_dir):
            raise RuntimeError("evidence journal already registered")
        protocol=_protocol(head,template,events_rel)
        protocol_path.parent.mkdir(parents=True,exist_ok=True)
        protocol_path.write_bytes(canonical(protocol))
        cmd(root,"add",protocol_rel)
        cmd(root,"commit","-m",f"vNext5R4 {head} prospective protocol pre-start")
        cmd(root,"push","origin","HEAD:"+branch)

        manifest=_manifest(
            head,branch,protocol_path.read_bytes(),
            source_sha,source_ref,trigger,template,
        )
        schedule=_make_event(events_dir,{
            "type":"SCHEDULE_REGISTERED",
            "idempotency_key":head+":schedule",
            "head":head,
            "start_utc":start.isoformat(),
            "evidence_branch":branch,
            "source_ref":source_ref,
            "workflow_trigger":trigger,
            "source_commit_sha":source_sha,
            "protocol_sha256":digest(protocol_path.read_bytes()),
            "trading_authority":False,
        })
        _,st=_publish(root,branch,events_dir,schedule)
        freeze=_make_event(events_dir,{
            "type":"CONFIG_FROZEN_PRESTART",
            "idempotency_key":head+":freeze",
            "head":head,
            "start_utc":start.isoformat(),
            "evidence_branch":branch,
            "source_ref":source_ref,
            "workflow_trigger":trigger,
            "source_commit_sha":source_sha,
            "manifest_sha256":digest(canonical(manifest)),
            "manifest":manifest,
            "trading_authority":False,
        })
        _,ft=_publish(root,branch,events_dir,freeze)
        if st>=start or ft>=start:
            raise RuntimeError("registration did not reach Rekor before START")
        v=_verify_branch(root,head,branch,protocol_rel,model_root)
        if v.start_utc!=start.isoformat():
            raise RuntimeError("verified registration start mismatch")
        return {
            "status":"REGISTERED_PRESTART",
            "head":head,"start_utc":start.isoformat(),
            "evidence_branch":branch,
            "source_sha":source_sha,
            "prospective_skill_proven":False,
            "trading_authority":False,
        }
    finally:
        _remove_worktree(root)


def _registration(root,head,branch,model_root):
    protocol_rel=f"predictive_vnext5_evidence/{head}/protocol.json"
    v=_verify_branch(root,head,branch,protocol_rel,model_root)
    return protocol_rel,v


def forecast(head,branch,model_root):
    if os.environ.get("GITHUB_EVENT_NAME")!="workflow_dispatch":
        raise RuntimeError("production forecast requires workflow_dispatch")
    root=_create_or_open_evidence_worktree(branch,os.environ["GITHUB_SHA"])
    try:
        protocol_rel,v=_registration(root,head,branch,model_root)
        start=datetime.fromisoformat(v.start_utc)
        now=datetime.now(UTC)
        anchor=nearest_closed_anchor(head,now)
        if anchor<start:
            return {"status":"PRESTART_NO_FORECAST","head":head}
        deadline=anchor+timedelta(
            minutes=json.loads((root/protocol_rel).read_text())
            ["head_config"]["forecast_deadline_minutes"]
        )
        events_dir=root/json.loads((root/protocol_rel).read_text())["events_dir"]
        slot=anchor.strftime("%Y%m%dT%H%M%SZ")
        prior=_events(events_dir)
        if any(e.get("type")=="FORECAST_ISSUED" and e.get("slot")==slot for e in prior):
            return {"status":"FORECAST_ALREADY_EXISTS","head":head,"slot":slot}
        if now>=deadline:
            missed=_make_event(events_dir,{
                "type":"SLOT_MISSED",
                "idempotency_key":"missed:"+slot,
                "head":head,
                "slot":slot,
                "reason":"NO_TIMELY_FORECAST",
                "deadline_utc":deadline.isoformat(),
                "trading_authority":False,
            })
            _publish(root,branch,events_dir,missed)
            return {"status":"SLOT_MISSED","head":head,"slot":slot}

        raw,values=fetch_forecast_raw(head,anchor,model_root)
        rawdir=root/f"predictive_vnext5_{head}_raw"/slot[:8]
        rawdir.mkdir(parents=True,exist_ok=True)
        rawpath=rawdir/(slot+"-forecast.json")
        rawpath.write_bytes(canonical(raw))
        event=_make_event(events_dir,{
            "type":"FORECAST_ISSUED",
            "idempotency_key":"forecast:"+slot,
            "slot":slot,
            "head":head,
            "anchor_utc":values["anchor_utc"],
            "due_utc":values["due_utc"],
            "query_type":"CANONICAL",
            "target_id":"CANONICAL_SIGMA_1_1_V1",
            "lower_sigma":1.0,
            "upper_sigma":1.0,
            "predictions":values["predictions"],
            "artifact_sha256":values["artifact_sha256"],
            "volatility":values["volatility"],
            "reference_price":values["reference_price"],
            "lower_price":values["lower_price"],
            "upper_price":values["upper_price"],
            "feature_sha256":values["feature_sha256"],
            "raw_path":str(rawpath.relative_to(root)),
            "raw_sha256":digest(rawpath.read_bytes()),
            "producer_mode":"PRODUCTION",
            "trading_authority":False,
        })
        commit,_=_publish(
            root,branch,events_dir,event,(rawpath,),deadline=deadline
        )
        receipt=_make_event(events_dir,{
            "type":"DELIVERY_CONFIRMED",
            "idempotency_key":"delivery:forecast:"+slot,
            "slot":slot,
            "head":head,
            "target_sequence":event["sequence"],
            "target_event_hash":digest(canonical(event)),
            "remote_commit_sha":commit,
            "trading_authority":False,
        })
        _publish(root,branch,events_dir,receipt,deadline=deadline)
        _verify_branch(root,head,branch,protocol_rel,model_root)
        return {
            "status":"FORECAST_PUBLISHED",
            "head":head,"slot":slot,
            "anchor_utc":values["anchor_utc"],
            "due_utc":values["due_utc"],
            "predictions":values["predictions"],
            "prospective_skill_proven":False,
            "trading_authority":False,
        }
    finally:
        _remove_worktree(root)


def outcome(head,branch,model_root):
    if os.environ.get("GITHUB_EVENT_NAME")!="workflow_dispatch":
        raise RuntimeError("production outcome requires workflow_dispatch")
    root=_create_or_open_evidence_worktree(branch,os.environ["GITHUB_SHA"])
    try:
        protocol_rel,_=_registration(root,head,branch,model_root)
        protocol=json.loads((root/protocol_rel).read_text())
        events_dir=root/protocol["events_dir"]
        prior=_events(events_dir)
        outcomes={e.get("slot") for e in prior if e.get("type")=="OUTCOME_RECORDED"}
        published=[]
        now=datetime.now(UTC)
        for forecast_event in prior:
            if forecast_event.get("type")!="FORECAST_ISSUED":
                continue
            slot=forecast_event["slot"]
            if slot in outcomes:
                continue
            due=datetime.fromisoformat(forecast_event["due_utc"])
            if due>now:
                continue
            anchor=datetime.fromisoformat(forecast_event["anchor_utc"])
            raw=fetch_outcome_raw(head,anchor,due)
            values=recompute_outcome_from_raw(
                head,raw,forecast_event["lower_price"],forecast_event["upper_price"]
            )
            rawdir=root/f"predictive_vnext5_{head}_raw"/slot[:8]
            rawdir.mkdir(parents=True,exist_ok=True)
            rawpath=rawdir/(slot+"-outcome.json")
            rawpath.write_bytes(canonical(raw))
            event=_make_event(events_dir,{
                "type":"OUTCOME_RECORDED",
                "idempotency_key":"outcome:"+slot,
                "slot":slot,
                "head":head,
                "anchor_utc":values["anchor_utc"],
                "due_utc":values["due_utc"],
                "query_type":"CANONICAL",
                "target_id":"CANONICAL_SIGMA_1_1_V1",
                "lower_sigma":1.0,
                "upper_sigma":1.0,
                "outcome_class":values["outcome_class"],
                "first_touch_time_utc":values["first_touch_time_utc"],
                "lower_price":values["lower_price"],
                "upper_price":values["upper_price"],
                "raw_path":str(rawpath.relative_to(root)),
                "raw_sha256":digest(rawpath.read_bytes()),
                "producer_mode":"PRODUCTION",
                "trading_authority":False,
            })
            _publish(root,branch,events_dir,event,(rawpath,))
            published.append(slot)
        _verify_branch(root,head,branch,protocol_rel,model_root)
        return {
            "status":"OUTCOMES_CHECKED",
            "head":head,"published_slots":published,
            "prospective_skill_proven":False,
            "trading_authority":False,
        }
    finally:
        _remove_worktree(root)


def main():
    action=os.environ.get("VNEXT5_ACTION")
    head=os.environ.get("VNEXT5_HEAD")
    branch=os.environ.get("VNEXT5_EVIDENCE_BRANCH")
    model_root=Path(os.environ["VNEXT5_MODEL_ROOT"]).resolve()
    if head not in HEADS:
        raise ValueError("invalid head")
    if not branch:
        raise ValueError("evidence branch missing")
    if action=="register":
        raw=os.environ.get("VNEXT5_START_UTC")
        if not raw:
            raise ValueError("START_UTC required for register")
        start=datetime.fromisoformat(raw.replace("Z","+00:00")).astimezone(UTC)
        out=register(head,branch,start,model_root)
    elif action=="forecast":
        out=forecast(head,branch,model_root)
    elif action=="outcome":
        out=outcome(head,branch,model_root)
    else:
        raise ValueError("invalid VNEXT5_ACTION")
    print(json.dumps(out,indent=2,sort_keys=True))


if __name__=="__main__":
    main()
