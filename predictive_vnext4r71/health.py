"""Read-only production health guard for BTC Predictive vNext4R7.1."""
from __future__ import annotations

import json
import os
import subprocess
from datetime import timedelta
from pathlib import Path

from predictive_vnext4r7.integrity import canonical
from predictive_vnext4r71.anchor import verify_latest_anchor
from predictive_vnext4r71.worker import (
    CONFIG,
    START,
    PRODUCTION_WORKFLOWS,
    EVIDENCE_ROOT,
    prior_events,
    slot_text,
    utcnow,
    verify_signature,
    verify_event_workflow_against_manifest,
    workflow_hash,
)


def _git(*args):
    return subprocess.run(
        ["git","-C",str(EVIDENCE_ROOT),*args],
        check=True,capture_output=True,text=True,timeout=180,
    ).stdout.strip()


def run(head: str) -> dict:
    if head not in CONFIG:
        raise ValueError("invalid head")
    cfg=CONFIG[head]
    events_with_time=prior_events(cfg)
    events=[e for e,_ in events_with_time]
    freezes=[
        e for e in events
        if e.get("type")=="CONFIG_FROZEN_PRESTART"
    ]
    if len(freezes)!=1:
        raise ValueError("exactly one signed freeze required")
    manifest=freezes[0].get("manifest")
    if not isinstance(manifest,dict):
        raise ValueError("signed manifest missing")

    deployment=manifest.get("deployment_workflows")
    if deployment!=list(PRODUCTION_WORKFLOWS):
        raise ValueError("signed deployment workflow set mismatch")
    signing_commit=os.environ.get("GITHUB_SHA","")
    for path in deployment:
        if workflow_hash(signing_commit,path)!=manifest["paths_sha256"].get(path):
            raise ValueError("current deployment bundle differs from freeze: "+path)

    checkpoint=EVIDENCE_ROOT/cfg["checkpoint"]
    checkpoint_bundle=checkpoint.with_suffix(".sigstore.json")
    checkpoint_state=None
    anchor=None
    if len(events)>=24:
        if not checkpoint.exists() or not checkpoint_bundle.exists():
            raise ValueError("checkpoint missing beyond frozen interval")
        checkpoint_doc=json.loads(checkpoint.read_bytes())
        cpseq=int(checkpoint_doc["verified_through_sequence"])
        if cpseq<=0 or len(events)-cpseq>=24:
            raise ValueError("checkpoint stale beyond frozen interval")
        current_tip=_git("rev-parse","HEAD")
        anchor=verify_latest_anchor(
            repo_root=EVIDENCE_ROOT,
            anchor_branch=cfg["anchor_branch"],
            head=head,
            manifest=manifest,
            workflow_path=cfg["forecast_workflow"],
            current_evidence_tip=current_tip,
            verify_blob=lambda p,b,e: verify_signature(p,b,cfg,e),
            verify_workflow_binding=verify_event_workflow_against_manifest,
        )
        if int(anchor["verified_through_sequence"])!=cpseq:
            raise ValueError("health anchor/checkpoint sequence mismatch")
        checkpoint_state={
            "verified_through_sequence":cpseq,
            "uncheckpointed_suffix_events":len(events)-cpseq,
        }

    now=utcnow()
    if now<START:
        if len(events)!=2:
            raise ValueError("pre-start journal must contain only authority events")
        return {
            "schema":"btc-predictive-vnext4r71-health-v1",
            "head":head,
            "status":"PRESTART_HEALTH_PASS",
            "event_count":len(events),
            "checkpoint":checkpoint_state,
            "anchor":anchor,
            "trading_authority":False,
        }

    by_type={}
    for e in events:
        by_type.setdefault(e.get("type"),{})[e.get("slot")]=e
    forecast=by_type.get("FORECAST_ISSUED",{})
    delivery=by_type.get("DELIVERY_CONFIRMED",{})
    missed=by_type.get("SLOT_MISSED",{})
    outcome=by_type.get("OUTCOME_RECORDED",{})

    cadence=cfg["cadence"]
    deadline=cfg["deadline"]
    horizon=cfg["horizon"]
    anchor_time=START
    checked=0
    while anchor_time+deadline<now:
        slot=slot_text(anchor_time)
        has_forecast=slot in forecast
        has_miss=slot in missed
        if has_forecast==has_miss:
            raise ValueError("forecast/miss lifecycle invalid: "+slot)
        if has_forecast:
            if slot not in delivery:
                raise ValueError("delivery missing: "+slot)
            grace=cadence+timedelta(minutes=5)
            if anchor_time+horizon+grace<now and slot not in outcome:
                raise ValueError("due outcome missing beyond grace: "+slot)
        checked+=1
        anchor_time+=cadence

    return {
        "schema":"btc-predictive-vnext4r71-health-v1",
        "head":head,
        "status":"POSTSTART_HEALTH_PASS",
        "event_count":len(events),
        "closed_deadline_slots":checked,
        "checkpoint":checkpoint_state,
        "anchor":anchor,
        "complete_deployment_bundle_bound":True,
        "trading_authority":False,
    }


def main():
    head=os.environ.get("BTC_VNEXT4R71_HEAD","")
    print(json.dumps(run(head),indent=2,sort_keys=True))


if __name__=="__main__":
    main()
