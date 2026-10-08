"""Real OIDC/Rekor E2E for vNext5R3 evidence -> canonical-row provenance.

This is engineering/provenance evidence only.  The short horizon is explicitly
E2E-only and cannot be used by production admission.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from predictive_vnext4r7.integrity import canonical, digest
from predictive_vnext4r71.crypto import bundle_time
from predictive_vnext5.verified_evidence import verify_evidence_snapshot
from predictive_vnext5.prospective_score import validate_canonical_row_schema

UTC=timezone.utc
ROOT=Path(__file__).resolve().parents[1]
REPO="sergeytren1984-ux/neora-b2b-v2-clean"
WORKFLOW=".github/workflows/btc-predictive-vnext5r3-provenance-e2e.yml"


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
    branch=os.environ["VNEXT5R3_E2E_BRANCH"]
    cmd("git","push","origin","HEAD:"+branch)
    local=cmd("git","rev-parse","HEAD")
    remote=cmd("git","ls-remote","origin","refs/heads/"+branch).split()[0]
    if local!=remote:
        raise RuntimeError("remote E2E publication mismatch")
    return local


def make_event(seq,previous,obj):
    return {
        "schema":"btc-predictive-vnext5r3-evidence-event-v1",
        "sequence":seq,
        "previous_hash":previous,
        "workflow_commit":os.environ["GITHUB_SHA"],
        "published_at_utc":datetime.now(UTC).isoformat(),
        **obj,
    }


def write_sign_event(events_dir,event,attachments=()):
    path=events_dir/f"{int(event['sequence']):08d}.json"
    bundle=path.with_suffix(".sigstore.json")
    path.write_bytes(canonical(event))
    sign(path,bundle)
    commit=push_paths(
        f"vNext5R3 provenance E2E #{event['sequence']} {event['type']}",
        path,bundle,*attachments
    )
    return path,commit


def wait_until(target):
    while True:
        left=(target-datetime.now(UTC)).total_seconds()
        if left<=0:
            return
        time.sleep(min(left,1.0))


def source_hash(source_sha,path):
    raw=subprocess.run(
        ["git","-C",str(ROOT),"show",f"{source_sha}:{path}"],
        check=True,capture_output=True,timeout=120
    ).stdout
    return digest(raw)


def main():
    source_sha=os.environ["GITHUB_SHA"]
    source_ref=os.environ["GITHUB_REF"]
    trigger=os.environ.get("GITHUB_EVENT_NAME","push")
    e2e_branch=os.environ["VNEXT5R3_E2E_BRANCH"]

    cmd("git","config","user.name","btc-vnext5r3-e2e[bot]")
    cmd("git","config","user.email","btc-vnext5r3-e2e[bot]@users.noreply.github.com")
    cmd("git","checkout","-B",e2e_branch,source_sha)
    cmd("git","push","-u","origin","HEAD:"+e2e_branch)

    run_id=os.environ.get("GITHUB_RUN_ID","local")
    events_dir=ROOT/f"vnext5r3_e2e_events_{run_id}"
    raw_dir=ROOT/"predictive_vnext5_1h_raw"/f"e2e-{run_id}"
    events_dir.mkdir(parents=True,exist_ok=True)
    raw_dir.mkdir(parents=True,exist_ok=True)

    start=(datetime.now(UTC)+timedelta(seconds=75)).replace(microsecond=0)
    horizon=timedelta(seconds=30)
    deadline=timedelta(seconds=25)
    due=start+horizon
    slot=start.strftime("%Y%m%dT%H%M%SZ")

    artifact={
        "1h":"9c24cb79f59a6a0b09e0f2980521e071c02cf749e4d14f88713b096fa569ed83"
    }
    protocol={
        "schema":"btc-predictive-vnext5r3-e2e-protocol-v1",
        "mode":"E2E",
        "head":"1h",
        "events_dir":str(events_dir.relative_to(ROOT)),
        "repository":REPO,
        "workflow_path":WORKFLOW,
        "canonical_target":{
            "query_type":"CANONICAL",
            "target_id":"CANONICAL_SIGMA_1_1_V1",
            "lower_sigma":1.0,
            "upper_sigma":1.0,
        },
        "head_config":{
            "horizon_seconds":30,
            "forecast_deadline_seconds":25,
            "candidates":["1h"],
            "artifact_sha256":artifact,
        },
        "trading_authority":False,
    }
    protocol_path=ROOT/f"vnext5r3_e2e_protocol_{run_id}.json"
    protocol_path.write_bytes(canonical(protocol))
    push_paths("vNext5R3 provenance E2E protocol",protocol_path)

    static_paths=[
        "predictive_vnext5/evidence_protocol_template.json",
        "predictive_vnext5/verified_evidence.py",
        "predictive_vnext5/prospective_admission.py",
        "predictive_vnext5/prospective_score.py",
        "predictive_vnext5/evaluation_supplement.json",
        "predictive_vnext5/frozen_evaluation_runtime.json",
        "predictive_vnext5/predictor.py",
        WORKFLOW,
    ]
    manifest={
        "schema":"btc-predictive-vnext5r3-e2e-manifest-v1",
        "source_commit_sha":source_sha,
        "source_ref":source_ref,
        "workflow_trigger":trigger,
        "evidence_branch":e2e_branch,
        "protocol_sha256":digest(protocol_path.read_bytes()),
        "paths_sha256":{
            p:source_hash(source_sha,p) for p in static_paths
        },
        "model_artifact_sha256":artifact,
        "trading_authority":False,
    }

    previous=None
    schedule=make_event(1,previous,{
        "type":"SCHEDULE_REGISTERED",
        "idempotency_key":"1h:schedule",
        "head":"1h",
        "start_utc":start.isoformat(),
        "evidence_branch":e2e_branch,
        "source_ref":source_ref,
        "workflow_trigger":trigger,
        "source_commit_sha":source_sha,
        "protocol_sha256":digest(protocol_path.read_bytes()),
        "trading_authority":False,
    })
    write_sign_event(events_dir,schedule)
    previous=digest(canonical(schedule))

    freeze=make_event(2,previous,{
        "type":"CONFIG_FROZEN_PRESTART",
        "idempotency_key":"1h:freeze",
        "head":"1h",
        "start_utc":start.isoformat(),
        "evidence_branch":e2e_branch,
        "source_ref":source_ref,
        "workflow_trigger":trigger,
        "source_commit_sha":source_sha,
        "manifest_sha256":digest(canonical(manifest)),
        "manifest":manifest,
        "trading_authority":False,
    })
    write_sign_event(events_dir,freeze)
    previous=digest(canonical(freeze))

    if bundle_time(events_dir/"00000001.sigstore.json")>=start:
        raise RuntimeError("schedule did not reach Rekor before E2E start")
    if bundle_time(events_dir/"00000002.sigstore.json")>=start:
        raise RuntimeError("freeze did not reach Rekor before E2E start")

    wait_until(start+timedelta(seconds=1))

    raw_f=raw_dir/(slot+".json")
    raw_f.write_bytes(canonical({
        "schema":"btc-predictive-vnext5r3-e2e-raw-v1",
        "slot":slot,
        "anchor_utc":start.isoformat(),
        "source":"E2E_SIGNED_PROVENANCE_ONLY",
    }))
    forecast=make_event(3,previous,{
        "type":"FORECAST_ISSUED",
        "idempotency_key":"forecast:"+slot,
        "slot":slot,
        "head":"1h",
        "anchor_utc":start.isoformat(),
        "due_utc":due.isoformat(),
        "query_type":"CANONICAL",
        "target_id":"CANONICAL_SIGMA_1_1_V1",
        "lower_sigma":1.0,
        "upper_sigma":1.0,
        "predictions":{"1h":[0.25,0.25,0.50,0.0]},
        "artifact_sha256":artifact,
        "volatility":0.002,
        "raw_path":str(raw_f.relative_to(ROOT)),
        "raw_sha256":digest(raw_f.read_bytes()),
        "probability_status":"E2E_PROVENANCE_ONLY",
        "trading_authority":False,
    })
    _,forecast_commit=write_sign_event(events_dir,forecast,(raw_f,))
    previous=digest(canonical(forecast))

    receipt=make_event(4,previous,{
        "type":"DELIVERY_CONFIRMED",
        "idempotency_key":"delivery:forecast:"+slot,
        "slot":slot,
        "head":"1h",
        "target_sequence":3,
        "target_event_hash":digest(canonical(forecast)),
        "remote_commit_sha":forecast_commit,
        "trading_authority":False,
    })
    write_sign_event(events_dir,receipt)
    previous=digest(canonical(receipt))

    wait_until(due+timedelta(seconds=1))

    raw_o=raw_dir/(slot+"-outcome.json")
    raw_o.write_bytes(canonical({
        "schema":"btc-predictive-vnext5r3-e2e-outcome-raw-v1",
        "slot":slot,
        "due_utc":due.isoformat(),
        "source":"E2E_SIGNED_PROVENANCE_ONLY",
    }))
    outcome=make_event(5,previous,{
        "type":"OUTCOME_RECORDED",
        "idempotency_key":"outcome:"+slot,
        "slot":slot,
        "head":"1h",
        "anchor_utc":start.isoformat(),
        "due_utc":due.isoformat(),
        "query_type":"CANONICAL",
        "target_id":"CANONICAL_SIGMA_1_1_V1",
        "lower_sigma":1.0,
        "upper_sigma":1.0,
        "outcome_class":"NEITHER",
        "raw_path":str(raw_o.relative_to(ROOT)),
        "raw_sha256":digest(raw_o.read_bytes()),
        "trading_authority":False,
    })
    write_sign_event(events_dir,outcome,(raw_o,))

    tip=cmd("git","rev-parse","HEAD")
    verified=verify_evidence_snapshot(
        root=ROOT,
        protocol_path=str(protocol_path.relative_to(ROOT)),
        events_dir=str(events_dir.relative_to(ROOT)),
        current_tip=tip,
        expected_branch=e2e_branch,
        allow_e2e_short_horizon=True,
    )
    if len(verified.rows)!=1:
        raise RuntimeError("E2E did not derive exactly one canonical row")
    row=verified.rows[0]
    validate_canonical_row_schema(row)
    if row["candidate_id"]!="1h" or row["outcome_class"]!=2:
        raise RuntimeError("derived canonical row content mismatch")
    if verified.governance["row_time_authority"]!="REKOR_INTEGRATED_TIME":
        raise RuntimeError("E2E row time is not Rekor-authoritative")
    if verified.governance["raw_remote_publication_verified"] is not True:
        raise RuntimeError("E2E raw publication proof missing")
    if verified.governance["forecast_delivery_receipt_verified"] is not True:
        raise RuntimeError("E2E delivery binding missing")

    # Demonstrate that the old arbitrary JSONL admission surface is disabled.
    proc=subprocess.run(
        [
            os.environ.get("PYTHON","python"),
            "predictive_vnext5/prospective_score.py",
            "--events-jsonl","/tmp/attacker.jsonl",
        ],
        cwd=ROOT,capture_output=True,text=True,
    )
    if proc.returncode==0 or "non-authoritative" not in (proc.stderr+proc.stdout):
        raise RuntimeError("standalone JSONL scorer unexpectedly authoritative")

    print(json.dumps({
        "status":"VNEXT5R3_SIGNED_PROVENANCE_E2E_PASS",
        "source_sha":source_sha,
        "evidence_branch":e2e_branch,
        "evidence_tip":tip,
        "verified_event_count":verified.governance["verified_event_count"],
        "derived_row_count":verified.governance["derived_row_count"],
        "full_cryptographic_replay":
            verified.governance["full_cryptographic_replay"],
        "all_event_signatures_verified":
            verified.governance["all_event_signatures_verified"],
        "all_rekor_inclusion_proofs_verified":
            verified.governance["all_rekor_inclusion_proofs_verified"],
        "raw_remote_publication_verified":
            verified.governance["raw_remote_publication_verified"],
        "forecast_delivery_receipt_verified":
            verified.governance["forecast_delivery_receipt_verified"],
        "row_time_authority":
            verified.governance["row_time_authority"],
        "standalone_jsonl_admission_forbidden":True,
        "prospective_skill_proven":False,
        "trading_authority":False,
    },indent=2,sort_keys=True))


if __name__=="__main__":
    main()
