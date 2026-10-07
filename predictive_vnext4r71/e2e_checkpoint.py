"""GitHub Actions E2E: real Sigstore events -> remote branch -> R7.1 checkpoint.

The branch is ephemeral and deleted by the workflow. This test uses real OIDC/Rekor
signatures and remote git publication without touching R6 or any production branch.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from predictive_vnext4r7.integrity import canonical, digest
from predictive_vnext4r71.admission import run_admission
from predictive_vnext4r71.checkpoint import event_files
from predictive_vnext4r71.journal_runtime import load_incremental_journal
from predictive_vnext4r71 import worker

UTC=timezone.utc
ROOT=Path(__file__).resolve().parents[1]
REPO="sergeytren1984-ux/neora-b2b-v2-clean"
WORKFLOW=".github/workflows/btc-predictive-vnext4r71-remediation.yml"


def cmd(*args,check=True):
    return subprocess.run(
        args,cwd=ROOT,check=check,capture_output=True,text=True,timeout=240
    ).stdout.strip()


def sign(path:Path,bundle:Path):
    subprocess.run(
        ["cosign","sign-blob","--yes","--bundle",str(bundle),str(path)],
        cwd=ROOT,check=True,capture_output=True,text=True,timeout=180
    )


def push_paths(message,*paths):
    for p in paths:
        cmd("git","add",str(Path(p).resolve().relative_to(ROOT)))
    cmd("git","commit","-m",message)
    branch=os.environ["R71_E2E_BRANCH"]
    cmd("git","push","origin","HEAD:"+branch)
    local=cmd("git","rev-parse","HEAD")
    remote=cmd("git","ls-remote","origin","refs/heads/"+branch).split()[0]
    if local!=remote:
        raise RuntimeError("E2E remote publication mismatch")
    return local


def make_event(seq,previous,obj):
    return {
        "schema":"btc-predictive-vnext4r71-event-v1",
        "sequence":seq,
        "previous_hash":previous,
        "workflow_commit":os.environ["GITHUB_SHA"],
        "published_at_utc":datetime.now(UTC).isoformat(),
        **obj,
    }


def write_sign_event(events_dir:Path,event:dict,attachments=(),push=True):
    path=events_dir/f"{int(event['sequence']):08d}.json"
    bundle=path.with_suffix(".sigstore.json")
    path.write_bytes(canonical(event))
    sign(path,bundle)
    if push:
        commit=push_paths(
            f"R7.1 E2E event #{event['sequence']}: {event['type']}",
            path,bundle,*attachments
        )
    else:
        for p in (path,bundle,*attachments):
            cmd("git","add",str(Path(p).resolve().relative_to(ROOT)))
        commit=None
    return path,commit


def wait_until(target:datetime):
    while True:
        left=(target-datetime.now(UTC)).total_seconds()
        if left<=0:
            return
        time.sleep(min(left,1.0))


def main():
    source_sha=os.environ["GITHUB_SHA"]
    e2e_branch=os.environ["R71_E2E_BRANCH"]
    anchor_branch=e2e_branch+"-anchors"
    source_ref=os.environ["GITHUB_REF"]
    trigger=os.environ.get("R71_EXPECTED_TRIGGER","push")

    cmd("git","config","user.name","btc-predictive-r71-e2e[bot]")
    cmd("git","config","user.email","btc-predictive-r71-e2e[bot]@users.noreply.github.com")
    cmd("git","checkout","-B",e2e_branch,source_sha)
    cmd("git","push","-u","origin","HEAD:"+e2e_branch)

    events_dir=ROOT/"r71_e2e_events"
    raw_dir=ROOT/"r71_e2e_raw"
    checkpoint=ROOT/"r71_e2e_checkpoint"/"1h.json"
    events_dir.mkdir(exist_ok=True)
    raw_dir.mkdir(exist_ok=True)

    # Give keyless signing + remote authority publication ample pre-start time.
    start=(datetime.now(UTC)+timedelta(seconds=75)).replace(microsecond=0)
    horizon=timedelta(seconds=30)
    deadline=timedelta(seconds=25)
    slot=start.strftime("%Y%m%dT%H%M%SZ")
    due=start+horizon

    protocol={
        "schema":"btc-predictive-vnext4r71-e2e-protocol-v1",
        "head":"1h",
        "start_utc":start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "admission_enabled":True,
        "selected_model":"E2E_DUMMY",
        "artifact_sha256":"a"*64,
        "baseline_sha256":"b"*64,
        "multiple_head_correction":{"per_head_alpha":1/60},
        "checkpointing":{
            "anchor_required":True,
            "anchor_branch":anchor_branch,
        },
        "admission":{
            "nonoverlap_window_hours":1,
            "minimum_calendar_days":42,
            "minimum_fixed_phase_nonoverlap_windows":500,
            "minimum_independent_volatility_episodes":12,
            "require_all_three_volatility_bins":True,
            "block_lengths_days":[7,14],
            "calibration_max_ece10_degradation_vs_primary":0.02,
            "volatility_episode_policy":{
                "minimum_duration_hours":3,
                "minimum_separation_hours":6,
            },
        },
        "trading_authority":False,
    }
    protocol_path=ROOT/"r71_e2e_protocol.json"
    protocol_path.write_bytes(canonical(protocol))
    push_paths("R7.1 E2E protocol",protocol_path)

    workflow_bytes=subprocess.run(
        ["git","-C",str(ROOT),"show",f"{source_sha}:{WORKFLOW}"],
        check=True,capture_output=True,timeout=120
    ).stdout
    manifest={
        "schema":"btc-predictive-vnext4r71-e2e-manifest-v1",
        "source_commit_sha":source_sha,
        "paths_sha256":{WORKFLOW:digest(workflow_bytes)},
    }

    previous=None
    schedule=make_event(1,previous,{
        "type":"SCHEDULE_REGISTERED",
        "idempotency_key":"1h:schedule",
        "head":"1h",
        "start_utc":start.isoformat(),
        "deadline_minutes":0,
        "protocol_sha256":digest(protocol_path.read_bytes()),
        "source_commit_sha":source_sha,
        "trading_authority":False,
    })
    write_sign_event(events_dir,schedule)
    previous=digest(canonical(schedule))

    freeze=make_event(2,previous,{
        "type":"CONFIG_FROZEN_PRESTART",
        "idempotency_key":"1h:freeze",
        "head":"1h",
        "start_utc":start.isoformat(),
        "manifest_sha256":digest(canonical(manifest)),
        "manifest":manifest,
        "trading_authority":False,
    })
    write_sign_event(events_dir,freeze)
    previous=digest(canonical(freeze))

    # Prove authority landed in Rekor before the prospective start.
    if worker.bundle_time(events_dir/"00000001.sigstore.json")>=start:
        raise RuntimeError("schedule Rekor time not pre-start")
    if worker.bundle_time(events_dir/"00000002.sigstore.json")>=start:
        raise RuntimeError("freeze Rekor time not pre-start")

    wait_until(start+timedelta(seconds=1))

    raw_f=raw_dir/"forecast.json"
    raw_f.write_bytes(canonical({"slot":slot,"source":"E2E","klines":[]}))
    forecast=make_event(3,previous,{
        "type":"FORECAST_ISSUED",
        "idempotency_key":"forecast:"+slot,
        "slot":slot,
        "head":"1h",
        "anchor_utc":start.isoformat(),
        "due_utc":due.isoformat(),
        "reference_price":100.0,
        "lower_price":99.0,
        "upper_price":101.0,
        "selected_model":"E2E_DUMMY",
        "class_distribution":{
            "lower_first":0.25,"upper_first":0.25,
            "neither":0.50,"ambiguous_same_bar":0.0,
        },
        "components":{},
        "control":{
            "primary_distribution":{
                "lower_first":0.25,"upper_first":0.25,
                "neither":0.50,"ambiguous_same_bar":0.0,
            },
            "volatility_bin":1,
        },
        "probability_status":"E2E_ONLY",
        "artifact_sha256":"a"*64,
        "baseline_sha256":"b"*64,
        "raw_path":str(raw_f.relative_to(ROOT)),
        "raw_sha256":digest(raw_f.read_bytes()),
        "trading_authority":False,
    })
    _,forecast_commit=write_sign_event(events_dir,forecast,(raw_f,))
    previous=digest(canonical(forecast))

    receipt=make_event(4,previous,{
        "type":"DELIVERY_CONFIRMED",
        "idempotency_key":"delivery:forecast:"+slot,
        "head":"1h",
        "slot":slot,
        "target_sequence":3,
        "target_event_hash":digest(canonical(forecast)),
        "remote_commit_sha":forecast_commit,
        "remote_confirmed_at_utc":datetime.now(UTC).isoformat(),
        "deadline_utc":(start+deadline).isoformat(),
        "trading_authority":False,
    })
    if datetime.now(UTC)>=start+deadline:
        raise RuntimeError("E2E forecast/receipt exceeded deadline")
    write_sign_event(events_dir,receipt)
    previous=digest(canonical(receipt))

    wait_until(due+timedelta(seconds=1))
    raw_o=raw_dir/"outcome.json"
    raw_o.write_bytes(canonical({"slot":slot,"due_utc":due.isoformat(),"klines":[]}))
    outcome=make_event(5,previous,{
        "type":"OUTCOME_RECORDED",
        "idempotency_key":"outcome:"+slot,
        "slot":slot,
        "head":"1h",
        "anchor_utc":start.isoformat(),
        "due_utc":due.isoformat(),
        "outcome_class":"NEITHER",
        "first_touch_time_utc":None,
        "lower_price":99.0,
        "upper_price":101.0,
        "raw_path":str(raw_o.relative_to(ROOT)),
        "raw_sha256":digest(raw_o.read_bytes()),
        "trading_authority":False,
    })
    write_sign_event(events_dir,outcome,(raw_o,))
    previous=digest(canonical(outcome))

    # Fill the journal to the frozen 24-event checkpoint interval. These are
    # explicit data-abstention evidence, not forecasts or outcomes.
    staged=[]
    for seq in range(6,25):
        fake_slot=(start+timedelta(minutes=seq)).strftime("%Y%m%dT%H%M%SZ")
        event=make_event(seq,previous,{
            "type":"ABSTAIN_DATA_INVALID",
            "idempotency_key":"abstain-data:"+fake_slot,
            "head":"1h",
            "slot":fake_slot,
            "reason":"E2E_CHECKPOINT_FILL",
            "retryable_before_deadline":False,
            "trading_authority":False,
        })
        path,_=write_sign_event(events_dir,event,push=False)
        staged.extend([path,path.with_suffix(".sigstore.json")])
        previous=digest(canonical(event))
    cmd("git","commit","-m","R7.1 E2E signed suffix through event 24")
    cmd("git","push","origin","HEAD:"+e2e_branch)

    os.environ["BTC_VNEXT4R71_EVIDENCE_ROOT"]=str(ROOT)
    os.environ["BTC_VNEXT4R71_START_UTC"]=start.isoformat()
    os.environ["BTC_VNEXT4R71_EXPECTED_REF"]=source_ref
    os.environ["BTC_VNEXT4R71_EXPECTED_TRIGGER"]=trigger
    # worker was imported before the dynamic E2E start was chosen.
    worker.EVIDENCE_ROOT=ROOT
    worker.START=start

    cfg={
        "head":"1h",
        "branch":e2e_branch,
        "events":str(events_dir.relative_to(ROOT)),
        "raw":str(raw_dir.relative_to(ROOT)),
        "checkpoint":str(checkpoint.relative_to(ROOT)),
        "anchor_branch":anchor_branch,
        "horizon":horizon,
        "deadline":deadline,
        "forecast_workflow":WORKFLOW,
        "outcome_workflow":WORKFLOW,
    }
    if not worker.maybe_checkpoint(cfg,"1h"):
        raise RuntimeError("worker did not create due checkpoint")
    if not checkpoint.exists() or not checkpoint.with_suffix(".sigstore.json").exists():
        raise RuntimeError("signed checkpoint files missing")

    # Recovery path must now use the checkpoint, not replay 24 old signatures.
    tip=cmd("git","rev-parse","HEAD")
    loaded=load_incremental_journal(
        repo_root=ROOT,
        events_dir=events_dir,
        checkpoint_path=checkpoint,
        checkpoint_bundle_path=checkpoint.with_suffix(".sigstore.json"),
        head="1h",
        horizon=horizon,
        issuance_deadline=deadline,
        start_utc=start,
        current_branch_tip=tip,
        forecast_workflow=WORKFLOW,
        outcome_workflow=WORKFLOW,
        verify_event_blob=lambda p,b,e: worker.verify_signature(p,b,cfg,e),
        verify_checkpoint_blob=lambda p,b,e: worker.verify_signature(p,b,cfg,e),
        verify_workflow_binding=worker.verify_event_workflow_against_manifest,
    )
    if not loaded["checkpoint_used"] or loaded["checkpoint_verified_through"]!=24:
        raise RuntimeError("checkpoint recovery path not active")
    if loaded["verified_suffix_event_count"]!=0:
        raise RuntimeError("unexpected suffix after fresh checkpoint")

    # Full admission path is mandatory and independent of checkpoint acceleration.
    report=run_admission(
        repo_root=str(ROOT),
        protocol_path=str(protocol_path.relative_to(ROOT)),
        events_dir=str(events_dir.relative_to(ROOT)),
        forecast_workflow=WORKFLOW,
        outcome_workflow=WORKFLOW,
        head="1h",
        start_utc=start,
        horizon=horizon,
        issuance_deadline=deadline,
        repository=REPO,
        expected_ref=source_ref,
        expected_trigger=trigger,
        current_tip=tip,
    )
    if report["governance"]["full_cryptographic_replay"] is not True:
        raise RuntimeError("admission skipped full cryptographic replay")
    if report["admission_ready"] is not False:
        raise RuntimeError("E2E short sample must not become admissible")

    print(json.dumps({
        "status":"R7_1_E2E_PASS",
        "evidence_branch":e2e_branch,
        "source_sha":source_sha,
        "event_count":len(event_files(events_dir)),
        "checkpoint_sequence":json.loads(checkpoint.read_text())["verified_through_sequence"],
        "checkpoint_remote_tip":tip,
        "anchor_branch":anchor_branch,
        "independent_checkpoint_anchor_verified":report["governance"]["independent_checkpoint_anchor_verified"],
        "admission_status":report["score"]["status"],
        "full_cryptographic_replay":report["governance"]["full_cryptographic_replay"],
    },indent=2,sort_keys=True))


if __name__=="__main__":
    main()
