"""Real OIDC/Rekor signed outcome-target negative E2E for vNext5R4.2.

A valid signer emits a correct 4h forecast/receipt and a malicious outcome whose
barriers, class and first-touch are jointly self-consistent under a different
target. The verifier must reject the outcome because only the verified forecast
barriers are authoritative for that slot.
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
from predictive_vnext4r71.crypto import bundle_time, make_blob_verifier
from predictive_vnext5.production_emitter import (
    MODEL_FILES, fetch_forecast_raw, fetch_outcome_raw,
    historical_replay_anchor, recompute_outcome_from_raw,
)
from predictive_vnext5.verified_evidence import verify_evidence_snapshot

UTC=timezone.utc
ROOT=Path(__file__).resolve().parents[1]
REPO="sergeytren1984-ux/neora-b2b-v2-clean"
WORKFLOW=".github/workflows/btc-predictive-vnext5r42-evidence.yml"
EVENT_SCHEMA="btc-predictive-vnext5r42-evidence-event-v1"


def cmd(*args,check=True,cwd=None):
    return subprocess.run(
        args,cwd=cwd or ROOT,check=check,capture_output=True,
        text=True,timeout=300
    ).stdout.strip()


def sign(path:Path,bundle:Path):
    subprocess.run(
        ["cosign","sign-blob","--yes","--bundle",str(bundle),str(path)],
        cwd=ROOT,check=True,capture_output=True,text=True,timeout=180
    )


def source_hash(source_sha,path):
    raw=subprocess.run(
        ["git","-C",str(ROOT),"show",f"{source_sha}:{path}"],
        check=True,capture_output=True,timeout=120
    ).stdout
    return digest(raw)


def make_event(seq,previous,obj):
    return {
        "schema":EVENT_SCHEMA,
        "sequence":seq,
        "previous_hash":previous,
        "workflow_commit":os.environ["GITHUB_SHA"],
        "published_at_utc":datetime.now(UTC).isoformat(),
        **obj,
    }


def push_paths(branch,message,*paths):
    for p in paths:
        cmd("git","add",str(Path(p).resolve().relative_to(ROOT)))
    cmd("git","commit","-m",message)
    cmd("git","push","origin","HEAD:"+branch)
    local=cmd("git","rev-parse","HEAD")
    remote=cmd("git","ls-remote","origin","refs/heads/"+branch).split()[0]
    if local!=remote:
        raise RuntimeError("negative outcome remote publication mismatch")
    return local


def write_sign_event(branch,events_dir,event,attachments=()):
    path=events_dir/f"{int(event['sequence']):08d}.json"
    bundle=path.with_suffix(".sigstore.json")
    path.write_bytes(canonical(event))
    sign(path,bundle)
    commit=push_paths(
        branch,
        f"vNext5R4.2 signed outcome-target negative #{event['sequence']} {event['type']}",
        path,bundle,*attachments,
    )
    return path,bundle,commit


def main():
    head="4h"
    model_root=Path(os.environ["VNEXT5_MODEL_ROOT"]).resolve()
    source_sha=os.environ["GITHUB_SHA"]
    source_ref=os.environ["GITHUB_REF"]
    trigger=os.environ.get("GITHUB_EVENT_NAME","push")
    run_id=os.environ.get("GITHUB_RUN_ID","local")
    branch=(
        f"btc-predictive-vnext5r42-outcome-negative-{run_id}-"
        f"attempt-{os.environ.get('GITHUB_RUN_ATTEMPT','1')}"
    )

    cmd("git","config","user.name","btc-vnext5r42-negative[bot]")
    cmd("git","config","user.email","btc-vnext5r42-negative[bot]@users.noreply.github.com")
    cmd("git","checkout","-B",branch,source_sha)
    cmd("git","push","-u","origin","HEAD:"+branch)

    template=json.loads(
        (ROOT/"predictive_vnext5/evidence_protocol_template.json").read_text()
    )
    cfg=template["heads"][head]
    events_dir=ROOT/f"vnext5r42_outcome_negative_{run_id}_events"
    raw_dir=ROOT/f"predictive_vnext5_{head}_raw"/f"outcome-negative-{run_id}"
    events_dir.mkdir(parents=True,exist_ok=True)
    raw_dir.mkdir(parents=True,exist_ok=True)

    protocol={
        "schema":"btc-predictive-vnext5r42-outcome-negative-protocol-v1",
        "mode":"MARKET_REPLAY_E2E",
        "head":head,
        "events_dir":str(events_dir.relative_to(ROOT)),
        "repository":REPO,
        "workflow_path":WORKFLOW,
        "canonical_target":template["canonical_target"],
        "head_config":cfg,
        "trading_authority":False,
    }
    protocol_path=ROOT/f"vnext5r42_outcome_negative_{run_id}_protocol.json"
    protocol_path.write_bytes(canonical(protocol))
    push_paths(branch,"vNext5R4.2 outcome-target negative protocol",protocol_path)

    execution=json.loads(
        (ROOT/"predictive_vnext5/execution_contract.json").read_text()
    )
    paths_sha256={
        p:source_hash(source_sha,p)
        for p in execution["required_source_paths"]
    }
    artifact={c:MODEL_FILES[c][1] for c in cfg["candidates"]}
    start=(datetime.now(UTC)+timedelta(minutes=5)).replace(microsecond=0)
    manifest={
        "schema":"btc-predictive-vnext5r42-outcome-negative-manifest-v1",
        "source_commit_sha":source_sha,
        "source_ref":source_ref,
        "workflow_trigger":trigger,
        "evidence_branch":branch,
        "protocol_sha256":digest(protocol_path.read_bytes()),
        "model_artifact_sha256":artifact,
        "paths_sha256":paths_sha256,
        "execution_contract_sha256":
            paths_sha256["predictive_vnext5/execution_contract.json"],
        "producer_mode":"MARKET_REPLAY_E2E",
        "trading_authority":False,
    }

    previous=None
    schedule=make_event(1,previous,{
        "type":"SCHEDULE_REGISTERED",
        "idempotency_key":"4h:schedule",
        "head":head,
        "start_utc":start.isoformat(),
        "evidence_branch":branch,
        "source_ref":source_ref,
        "workflow_trigger":trigger,
        "source_commit_sha":source_sha,
        "protocol_sha256":digest(protocol_path.read_bytes()),
        "trading_authority":False,
    })
    _,sb,_=write_sign_event(branch,events_dir,schedule)
    previous=digest(canonical(schedule))

    freeze=make_event(2,previous,{
        "type":"CONFIG_FROZEN_PRESTART",
        "idempotency_key":"4h:freeze",
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
    _,fb,_=write_sign_event(branch,events_dir,freeze)
    previous=digest(canonical(freeze))
    if bundle_time(sb)>=start or bundle_time(fb)>=start:
        raise RuntimeError("negative authority events not pre-start")

    anchor=historical_replay_anchor(head)
    raw_f,forecast_values=fetch_forecast_raw(head,anchor,model_root)
    slot=anchor.strftime("%Y%m%dT%H%M%SZ")
    raw_f_path=raw_dir/(slot+"-forecast.json")
    raw_f_path.write_bytes(canonical(raw_f))
    forecast=make_event(3,previous,{
        "type":"FORECAST_ISSUED",
        "idempotency_key":"forecast:"+slot,
        "slot":slot,
        "head":head,
        "anchor_utc":forecast_values["anchor_utc"],
        "due_utc":forecast_values["due_utc"],
        "query_type":"CANONICAL",
        "target_id":"CANONICAL_SIGMA_1_1_V1",
        "lower_sigma":1.0,
        "upper_sigma":1.0,
        "predictions":forecast_values["predictions"],
        "artifact_sha256":forecast_values["artifact_sha256"],
        "volatility":forecast_values["volatility"],
        "reference_price":forecast_values["reference_price"],
        "lower_price":forecast_values["lower_price"],
        "upper_price":forecast_values["upper_price"],
        "feature_sha256":forecast_values["feature_sha256"],
        "raw_path":str(raw_f_path.relative_to(ROOT)),
        "raw_sha256":digest(raw_f_path.read_bytes()),
        "producer_mode":"MARKET_REPLAY_E2E",
        "trading_authority":False,
    })
    _,_,forecast_commit=write_sign_event(
        branch,events_dir,forecast,(raw_f_path,)
    )
    previous=digest(canonical(forecast))

    receipt=make_event(4,previous,{
        "type":"DELIVERY_CONFIRMED",
        "idempotency_key":"delivery:forecast:"+slot,
        "slot":slot,
        "head":head,
        "target_sequence":3,
        "target_event_hash":digest(canonical(forecast)),
        "remote_commit_sha":forecast_commit,
        "trading_authority":False,
    })
    write_sign_event(branch,events_dir,receipt)
    previous=digest(canonical(receipt))

    due=datetime.fromisoformat(forecast_values["due_utc"])
    raw_o=fetch_outcome_raw(head,anchor,due)
    raw_o_path=raw_dir/(slot+"-outcome.json")
    raw_o_path.write_bytes(canonical(raw_o))

    # Joint attack: choose a different target whose label is internally valid.
    top=max(float(k[2]) for k in raw_o["klines"])
    malicious_lower=top+100.0
    malicious_upper=top+1000.0
    malicious=recompute_outcome_from_raw(
        head,raw_o,malicious_lower,malicious_upper
    )
    if (
        malicious_lower==forecast_values["lower_price"]
        or malicious_upper==forecast_values["upper_price"]
    ):
        raise RuntimeError("negative barriers unexpectedly equal forecast target")

    outcome=make_event(5,previous,{
        "type":"OUTCOME_RECORDED",
        "idempotency_key":"outcome:"+slot,
        "slot":slot,
        "head":head,
        "anchor_utc":malicious["anchor_utc"],
        "due_utc":malicious["due_utc"],
        "query_type":"CANONICAL",
        "target_id":"CANONICAL_SIGMA_1_1_V1",
        "lower_sigma":1.0,
        "upper_sigma":1.0,
        "outcome_class":malicious["outcome_class"],
        "first_touch_time_utc":malicious["first_touch_time_utc"],
        "lower_price":malicious_lower,
        "upper_price":malicious_upper,
        "raw_path":str(raw_o_path.relative_to(ROOT)),
        "raw_sha256":digest(raw_o_path.read_bytes()),
        "producer_mode":"MARKET_REPLAY_E2E",
        "trading_authority":False,
    })
    outcome_path,outcome_bundle,_=write_sign_event(
        branch,events_dir,outcome,(raw_o_path,)
    )

    # Prove the malicious event itself has a genuine allowed signer identity.
    verify_blob=make_blob_verifier(
        repository=REPO,
        workflow_path=WORKFLOW,
        ref=source_ref,
        trigger=trigger,
        repo_root=ROOT,
    )
    verify_blob(outcome_path,outcome_bundle,outcome)

    tip=cmd("git","rev-parse","HEAD")
    source_parent=Path(tempfile.mkdtemp(prefix="vnext5r42-outcome-source-"))
    source_checkout=source_parent/"worktree"
    try:
        cmd(
            "git","worktree","add","--detach",str(source_checkout),source_sha,
            cwd=ROOT,
        )
        try:
            verify_evidence_snapshot(
                root=ROOT,
                protocol_path=str(protocol_path.relative_to(ROOT)),
                events_dir=str(events_dir.relative_to(ROOT)),
                current_tip=tip,
                expected_branch=branch,
                allow_market_replay=True,
                source_checkout=source_checkout,
                model_root=model_root,
                require_numerical_replay=True,
            )
        except ValueError as ex:
            rejection=str(ex)
            if "outcome barrier differs from verified forecast" not in rejection:
                raise
        else:
            raise RuntimeError(
                "joint outcome barrier+label+touch attack unexpectedly accepted"
            )
    finally:
        subprocess.run(
            ["git","-C",str(ROOT),"worktree","remove","--force",str(source_checkout)],
            check=False,capture_output=True,text=True,timeout=180,
        )
        shutil.rmtree(source_parent,ignore_errors=True)

    print(json.dumps({
        "status":"VNEXT5R42_SIGNED_OUTCOME_TARGET_NEGATIVE_E2E_PASS",
        "source_sha":source_sha,
        "evidence_branch":branch,
        "evidence_tip":tip,
        "malicious_outcome_signature_verified":True,
        "forecast_lower_price":forecast_values["lower_price"],
        "forecast_upper_price":forecast_values["upper_price"],
        "malicious_lower_price":malicious_lower,
        "malicious_upper_price":malicious_upper,
        "malicious_outcome_class":malicious["outcome_class"],
        "malicious_first_touch_time_utc":malicious["first_touch_time_utc"],
        "semantic_rejection":rejection,
        "canonical_rows_derived":0,
        "prospective_skill_proven":False,
        "trading_authority":False,
    },indent=2,sort_keys=True))


if __name__=="__main__":
    main()
