"""Real-market signed engineering E2E for vNext5R4.

Uses the frozen production numerical emitter with actual Binance closed candles
and exact immutable model binaries.  It signs a historical completed market
replay under the same frozen workflow identity for all heads.  This proves the
artifact/raw -> feature -> prediction -> barrier -> outcome chain, but is
explicitly non-prospective and has no admission/trading authority.
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
    MODEL_FILES, fetch_forecast_raw, fetch_outcome_raw,
    historical_replay_anchor, recompute_outcome_from_raw,
)
from predictive_vnext5.verified_evidence import verify_evidence_snapshot

UTC=timezone.utc
ROOT=Path(__file__).resolve().parents[1]
REPO="sergeytren1984-ux/neora-b2b-v2-clean"
WORKFLOW=".github/workflows/btc-predictive-vnext5r4-evidence.yml"


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
        "schema":"btc-predictive-vnext5r4-evidence-event-v1",
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
        raise RuntimeError("remote market-replay publication mismatch")
    return local


def write_sign_event(branch,events_dir,event,attachments=()):
    path=events_dir/f"{int(event['sequence']):08d}.json"
    bundle=path.with_suffix(".sigstore.json")
    path.write_bytes(canonical(event))
    sign(path,bundle)
    commit=push_paths(
        branch,
        f"vNext5R4 {event['head']} market replay #{event['sequence']} {event['type']}",
        path,bundle,*attachments,
    )
    return path,commit


def main():
    head=os.environ["VNEXT5R4_E2E_HEAD"]
    if head not in {"1h","4h","24h"}:
        raise ValueError("invalid E2E head")
    model_root=Path(os.environ["VNEXT5_MODEL_ROOT"]).resolve()
    source_sha=os.environ["GITHUB_SHA"]
    source_ref=os.environ["GITHUB_REF"]
    trigger=os.environ.get("GITHUB_EVENT_NAME","push")
    run_id=os.environ.get("GITHUB_RUN_ID","local")
    branch=f"btc-predictive-vnext5r4-market-e2e-{run_id}-{head}-attempt-{os.environ.get('GITHUB_RUN_ATTEMPT','1')}"

    cmd("git","config","user.name","btc-vnext5r4-e2e[bot]")
    cmd("git","config","user.email","btc-vnext5r4-e2e[bot]@users.noreply.github.com")
    cmd("git","checkout","-B",branch,source_sha)
    cmd("git","push","-u","origin","HEAD:"+branch)

    template=json.loads(
        (ROOT/"predictive_vnext5/evidence_protocol_template.json").read_text()
    )
    cfg=template["heads"][head]
    events_dir=ROOT/f"vnext5r4_market_e2e_{run_id}_{head}_events"
    raw_dir=ROOT/f"predictive_vnext5_{head}_raw"/f"market-e2e-{run_id}"
    events_dir.mkdir(parents=True,exist_ok=True)
    raw_dir.mkdir(parents=True,exist_ok=True)

    protocol={
        "schema":"btc-predictive-vnext5r4-market-replay-protocol-v1",
        "mode":"MARKET_REPLAY_E2E",
        "head":head,
        "events_dir":str(events_dir.relative_to(ROOT)),
        "repository":REPO,
        "workflow_path":WORKFLOW,
        "canonical_target":template["canonical_target"],
        "head_config":cfg,
        "trading_authority":False,
    }
    protocol_path=ROOT/f"vnext5r4_market_e2e_{run_id}_{head}_protocol.json"
    protocol_path.write_bytes(canonical(protocol))
    push_paths(branch,f"vNext5R4 {head} market replay protocol",protocol_path)

    execution=json.loads(
        (ROOT/"predictive_vnext5/execution_contract.json").read_text()
    )
    required=execution["required_source_paths"]
    paths_sha256={p:source_hash(source_sha,p) for p in required}
    artifact={c:MODEL_FILES[c][1] for c in cfg["candidates"]}
    start=(datetime.now(UTC)+timedelta(minutes=5)).replace(microsecond=0)
    manifest={
        "schema":"btc-predictive-vnext5r4-market-replay-manifest-v1",
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
    write_sign_event(branch,events_dir,schedule)
    previous=digest(canonical(schedule))

    freeze=make_event(2,previous,{
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
    write_sign_event(branch,events_dir,freeze)
    previous=digest(canonical(freeze))

    if bundle_time(events_dir/"00000001.sigstore.json")>=start:
        raise RuntimeError("market replay schedule not in Rekor before registration start")
    if bundle_time(events_dir/"00000002.sigstore.json")>=start:
        raise RuntimeError("market replay freeze not in Rekor before registration start")

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
    _,forecast_commit=write_sign_event(
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
    outcome_values=recompute_outcome_from_raw(
        head,raw_o,forecast_values["lower_price"],forecast_values["upper_price"]
    )
    raw_o_path=raw_dir/(slot+"-outcome.json")
    raw_o_path.write_bytes(canonical(raw_o))
    outcome=make_event(5,previous,{
        "type":"OUTCOME_RECORDED",
        "idempotency_key":"outcome:"+slot,
        "slot":slot,
        "head":head,
        "anchor_utc":outcome_values["anchor_utc"],
        "due_utc":outcome_values["due_utc"],
        "query_type":"CANONICAL",
        "target_id":"CANONICAL_SIGMA_1_1_V1",
        "lower_sigma":1.0,
        "upper_sigma":1.0,
        "outcome_class":outcome_values["outcome_class"],
        "first_touch_time_utc":outcome_values["first_touch_time_utc"],
        "lower_price":outcome_values["lower_price"],
        "upper_price":outcome_values["upper_price"],
        "raw_path":str(raw_o_path.relative_to(ROOT)),
        "raw_sha256":digest(raw_o_path.read_bytes()),
        "producer_mode":"MARKET_REPLAY_E2E",
        "trading_authority":False,
    })
    write_sign_event(branch,events_dir,outcome,(raw_o_path,))

    tip=cmd("git","rev-parse","HEAD")
    source_parent=Path(tempfile.mkdtemp(prefix="vnext5r4-source-e2e-"))
    source_checkout=source_parent/"worktree"
    try:
        cmd(
            "git","worktree","add","--detach",str(source_checkout),source_sha,
            cwd=ROOT,
        )
        verified=verify_evidence_snapshot(
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
    finally:
        subprocess.run(
            ["git","-C",str(ROOT),"worktree","remove","--force",str(source_checkout)],
            check=False,capture_output=True,text=True,timeout=180,
        )
        shutil.rmtree(source_parent,ignore_errors=True)

    if len(verified.rows)!=len(cfg["candidates"]):
        raise RuntimeError("market replay derived wrong candidate-row count")
    if verified.governance.get("numerical_provenance_replayed") is not True:
        raise RuntimeError("numerical provenance replay missing")
    if verified.governance.get("admission_eligible") is not False:
        raise RuntimeError("market replay unexpectedly admission eligible")

    result={
        "status":"VNEXT5R4_REAL_MARKET_SIGNED_NUMERICAL_E2E_PASS",
        "head":head,
        "source_sha":source_sha,
        "evidence_branch":branch,
        "evidence_tip":tip,
        "anchor_utc":anchor.isoformat(),
        "due_utc":due.isoformat(),
        "reference_price":forecast_values["reference_price"],
        "volatility":forecast_values["volatility"],
        "lower_price":forecast_values["lower_price"],
        "upper_price":forecast_values["upper_price"],
        "predictions":forecast_values["predictions"],
        "outcome_class":outcome_values["outcome_class"],
        "first_touch_time_utc":outcome_values["first_touch_time_utc"],
        "signed_event_count":5,
        "numerical_provenance_replayed":True,
        "real_market_raw":True,
        "admission_eligible":False,
        "prospective_skill_proven":False,
        "trading_authority":False,
    }
    out=ROOT/f"vnext5r4_market_e2e_result_{head}.json"
    out.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
    print(json.dumps(result,indent=2,sort_keys=True))


if __name__=="__main__":
    main()
