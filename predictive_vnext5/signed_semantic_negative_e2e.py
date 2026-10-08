"""Real OIDC/Rekor signed semantic-negative E2E for vNext5R4.1.

The job proves that an event genuinely signed by the allowed workflow identity is
still rejected when it carries undeclared custom-target annotations.  The same
event-schema attack is also repeated across the complete 4h 42-day/252-window
grid locally; none may reach canonical row derivation.
"""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from predictive_vnext4r7.integrity import canonical, digest
from predictive_vnext4r71.crypto import bundle_time, make_blob_verifier
from predictive_vnext5.verified_evidence import (
    _validate_exact_event_schema,
    verify_evidence_snapshot,
)

UTC=timezone.utc
ROOT=Path(__file__).resolve().parents[1]
REPO="sergeytren1984-ux/neora-b2b-v2-clean"
WORKFLOW=".github/workflows/btc-predictive-vnext5r41-evidence.yml"
EVENT_SCHEMA="btc-predictive-vnext5r41-evidence-event-v1"


def cmd(*args,check=True):
    return subprocess.run(
        args,cwd=ROOT,check=check,capture_output=True,text=True,timeout=240
    ).stdout.strip()


def sign(path:Path,bundle:Path):
    subprocess.run(
        ["cosign","sign-blob","--yes","--bundle",str(bundle),str(path)],
        cwd=ROOT,check=True,capture_output=True,text=True,timeout=180
    )


def push(branch,message,*paths):
    for p in paths:
        cmd("git","add",str(Path(p).resolve().relative_to(ROOT)))
    cmd("git","commit","-m",message)
    cmd("git","push","origin","HEAD:"+branch)
    local=cmd("git","rev-parse","HEAD")
    remote=cmd("git","ls-remote","origin","refs/heads/"+branch).split()[0]
    if local!=remote:
        raise RuntimeError("negative E2E remote publication mismatch")
    return local


def source_hash(source_sha,path):
    return digest(subprocess.run(
        ["git","-C",str(ROOT),"show",f"{source_sha}:{path}"],
        check=True,capture_output=True,timeout=120
    ).stdout)


def event(seq,previous,obj):
    return {
        "schema":EVENT_SCHEMA,
        "sequence":seq,
        "previous_hash":previous,
        "workflow_commit":os.environ["GITHUB_SHA"],
        "published_at_utc":datetime.now(UTC).isoformat(),
        **obj,
    }


def write_signed(branch,events_dir,obj):
    path=events_dir/f"{obj['sequence']:08d}.json"
    bundle=path.with_suffix(".sigstore.json")
    path.write_bytes(canonical(obj))
    sign(path,bundle)
    push(
        branch,
        f"vNext5R4.1 signed semantic negative #{obj['sequence']} {obj['type']}",
        path,bundle,
    )
    return path,bundle


def malicious_forecast(seq,previous,anchor,artifact):
    slot=anchor.strftime("%Y%m%dT%H%M%SZ")
    return event(seq,previous,{
        "type":"FORECAST_ISSUED",
        "idempotency_key":"forecast:"+slot,
        "head":"4h",
        "slot":slot,
        "anchor_utc":anchor.isoformat(),
        "due_utc":(anchor+timedelta(hours=4)).isoformat(),
        "query_type":"CANONICAL",
        "target_id":"CANONICAL_SIGMA_1_1_V1",
        "lower_sigma":1.0,
        "upper_sigma":1.0,
        "predictions":{"4h":[0.25,0.25,0.50,0.0]},
        "artifact_sha256":artifact,
        "volatility":0.002,
        "reference_price":83000.0,
        "lower_price":82500.0,
        "upper_price":83500.0,
        "feature_sha256":"1"*64,
        "raw_path":"predictive_vnext5_4h_raw/attack.json",
        "raw_sha256":"2"*64,
        "producer_mode":"MARKET_REPLAY_E2E",
        "custom_zone":[82000.0,87000.0],
        "actual_query_type":"CUSTOM_ZONE",
        "trading_authority":False,
    })


def main():
    source_sha=os.environ["GITHUB_SHA"]
    source_ref=os.environ["GITHUB_REF"]
    trigger=os.environ.get("GITHUB_EVENT_NAME","push")
    run_id=os.environ.get("GITHUB_RUN_ID","local")
    branch=(
        f"btc-predictive-vnext5r41-a5-negative-{run_id}-"
        f"attempt-{os.environ.get('GITHUB_RUN_ATTEMPT','1')}"
    )

    cmd("git","config","user.name","btc-vnext5r41-negative[bot]")
    cmd(
        "git","config","user.email",
        "btc-vnext5r41-negative[bot]@users.noreply.github.com",
    )
    cmd("git","checkout","-B",branch,source_sha)
    cmd("git","push","-u","origin","HEAD:"+branch)

    template=json.loads(
        (ROOT/"predictive_vnext5/evidence_protocol_template.json").read_text()
    )
    cfg=template["heads"]["4h"]
    events_dir=ROOT/f"vnext5r41_a5_negative_{run_id}_events"
    events_dir.mkdir(parents=True,exist_ok=True)

    protocol={
        "schema":"btc-predictive-vnext5r41-a5-negative-protocol-v1",
        "mode":"MARKET_REPLAY_E2E",
        "head":"4h",
        "events_dir":str(events_dir.relative_to(ROOT)),
        "repository":REPO,
        "workflow_path":WORKFLOW,
        "canonical_target":template["canonical_target"],
        "head_config":cfg,
        "trading_authority":False,
    }
    protocol_path=ROOT/f"vnext5r41_a5_negative_{run_id}_protocol.json"
    protocol_path.write_bytes(canonical(protocol))
    push(branch,"vNext5R4.1 A5 negative protocol",protocol_path)

    execution=json.loads(
        (ROOT/"predictive_vnext5/execution_contract.json").read_text()
    )
    paths={
        p:source_hash(source_sha,p)
        for p in execution["required_source_paths"]
    }
    artifact=cfg["artifact_sha256"]
    start=(datetime.now(UTC)+timedelta(minutes=5)).replace(microsecond=0)
    manifest={
        "schema":"btc-predictive-vnext5r41-a5-negative-manifest-v1",
        "source_commit_sha":source_sha,
        "source_ref":source_ref,
        "workflow_trigger":trigger,
        "evidence_branch":branch,
        "protocol_sha256":digest(protocol_path.read_bytes()),
        "model_artifact_sha256":artifact,
        "paths_sha256":paths,
        "execution_contract_sha256":
            paths["predictive_vnext5/execution_contract.json"],
        "producer_mode":"MARKET_REPLAY_E2E",
        "trading_authority":False,
    }

    schedule=event(1,None,{
        "type":"SCHEDULE_REGISTERED",
        "idempotency_key":"4h:schedule",
        "head":"4h",
        "start_utc":start.isoformat(),
        "evidence_branch":branch,
        "source_ref":source_ref,
        "workflow_trigger":trigger,
        "source_commit_sha":source_sha,
        "protocol_sha256":digest(protocol_path.read_bytes()),
        "trading_authority":False,
    })
    _,sb=write_signed(branch,events_dir,schedule)
    previous=digest(canonical(schedule))

    freeze=event(2,previous,{
        "type":"CONFIG_FROZEN_PRESTART",
        "idempotency_key":"4h:freeze",
        "head":"4h",
        "start_utc":start.isoformat(),
        "evidence_branch":branch,
        "source_ref":source_ref,
        "workflow_trigger":trigger,
        "source_commit_sha":source_sha,
        "manifest_sha256":digest(canonical(manifest)),
        "manifest":manifest,
        "trading_authority":False,
    })
    _,fb=write_signed(branch,events_dir,freeze)
    previous=digest(canonical(freeze))
    if bundle_time(sb)>=start or bundle_time(fb)>=start:
        raise RuntimeError("negative E2E authority events not pre-start")

    attack=malicious_forecast(
        3,previous,
        datetime(2026,10,8,8,0,tzinfo=UTC),
        artifact,
    )
    attack_path,attack_bundle=write_signed(branch,events_dir,attack)

    # Prove the malformed event was genuinely signed by the allowed workflow
    # identity before asking the semantic verifier to reject it.
    verify_blob=make_blob_verifier(
        repository=REPO,
        workflow_path=WORKFLOW,
        ref=source_ref,
        trigger=trigger,
        repo_root=ROOT,
    )
    verify_blob(attack_path,attack_bundle,attack)

    # Full 4h 42-day primary grid: every identically structured malicious
    # event must fail at the signed-event boundary before row derivation.
    rejected=0
    grid_start=datetime(2026,10,12,0,0,tzinfo=UTC)
    for i in range(252):
        probe=malicious_forecast(
            3,previous,grid_start+timedelta(hours=4*i),artifact
        )
        try:
            _validate_exact_event_schema(probe)
        except ValueError as ex:
            if "forbidden fields" not in str(ex):
                raise
            rejected+=1
    if rejected!=252:
        raise RuntimeError("not all full-grid A5 attacks were rejected")

    tip=cmd("git","rev-parse","HEAD")
    try:
        verify_evidence_snapshot(
            root=ROOT,
            protocol_path=str(protocol_path.relative_to(ROOT)),
            events_dir=str(events_dir.relative_to(ROOT)),
            current_tip=tip,
            expected_branch=branch,
            allow_market_replay=True,
            source_checkout=ROOT,
            model_root=Path(os.environ["VNEXT5_MODEL_ROOT"]),
            require_numerical_replay=True,
        )
    except ValueError as ex:
        if "forbidden fields" not in str(ex):
            raise
        rejection=str(ex)
    else:
        raise RuntimeError("signed A5 custom-field attack unexpectedly accepted")

    print(json.dumps({
        "status":"VNEXT5R41_SIGNED_A5_NEGATIVE_E2E_PASS",
        "source_sha":source_sha,
        "evidence_branch":branch,
        "evidence_tip":tip,
        "malicious_event_signature_verified":True,
        "full_grid_4h_attack_count":252,
        "full_grid_4h_rejected_count":rejected,
        "semantic_rejection":rejection,
        "canonical_rows_derived":0,
        "prospective_skill_proven":False,
        "trading_authority":False,
    },indent=2,sort_keys=True))


if __name__=="__main__":
    main()
