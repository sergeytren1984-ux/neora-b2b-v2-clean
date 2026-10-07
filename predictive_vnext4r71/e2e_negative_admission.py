"""Real OIDC/Rekor negative E2E attacks against the mandatory R7.1 admission path."""
from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from predictive_vnext4r7.integrity import canonical, digest
from predictive_vnext4r71.admission import run_admission
from predictive_vnext4r71.integrity import (
    REQUIRED_PROTOCOLS,
    REQUIRED_PRODUCTION_WORKFLOWS,
)

UTC=timezone.utc
ROOT=Path(__file__).resolve().parents[1]
REPO="sergeytren1984-ux/neora-b2b-v2-clean"
WORKFLOW=".github/workflows/btc-predictive-vnext4r71-remediation.yml"
BASE=ROOT/"r71_negative_e2e"
RUN_ID=os.environ.get("GITHUB_RUN_ID","local")
NEG_BRANCH=os.environ.get(
    "R72_NEGATIVE_E2E_BRANCH",
    "btc-predictive-vnext4r72-negative-e2e-"+RUN_ID,
)
RAW_ROOT=ROOT/"predictive_vnext4r71_1h_raw"/("r72-negative-"+RUN_ID)


def sign(path:Path,bundle:Path):
    subprocess.run(
        ["cosign","sign-blob","--yes","--bundle",str(bundle),str(path)],
        cwd=ROOT,check=True,capture_output=True,text=True,timeout=180,
    )


def make_event(seq,previous,obj):
    return {
        "schema":"btc-predictive-vnext4r71-event-v1",
        "sequence":seq,
        "previous_hash":previous,
        "workflow_commit":os.environ["GITHUB_SHA"],
        "published_at_utc":datetime.now(UTC).isoformat(),
        **obj,
    }


def write_signed(events_dir:Path,event:dict):
    path=events_dir/f"{int(event['sequence']):08d}.json"
    bundle=path.with_suffix(".sigstore.json")
    path.write_bytes(canonical(event))
    sign(path,bundle)
    return path,bundle


def protocol(start:datetime,*,enabled=True):
    return {
        "schema":"btc-predictive-vnext4r71-negative-e2e-protocol-v1",
        "head":"1h",
        "start_utc":start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "admission_enabled":bool(enabled),
        "selected_model":"NEGATIVE_E2E_DUMMY",
        "issuance_deadline_seconds":600,
        "target":{"horizon_seconds":60},
        "workflows":{"forecast":WORKFLOW,"outcome":WORKFLOW},
        "event_signature_binding":{
            "github_workflow_repository":REPO,
            "github_workflow_ref":os.environ["GITHUB_REF"],
            "github_workflow_trigger":os.environ.get(
                "R71_EXPECTED_TRIGGER","push"
            ),
        },
        "artifact_sha256":"a"*64,
        "baseline_sha256":"b"*64,
        "multiple_head_correction":{"per_head_alpha":1/60},
        "checkpointing":{
            "interval_events":24,
            "anchor_required":True,
            "anchor_branch":"unused-negative-e2e-anchor",
            "checkpoint_path":"unused-negative-e2e-checkpoint.json",
        },
        "signed_manifest_requirements":{
            "all_protocols_required":list(REQUIRED_PROTOCOLS),
            "all_production_workflows_required":list(REQUIRED_PRODUCTION_WORKFLOWS),
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


def write_protocol(case_dir:Path,obj:dict):
    p=case_dir/"protocol.json"
    p.write_bytes(canonical(obj))
    return p


def authority_events(
    events_dir:Path,
    start:datetime,
    protocol_path:Path,
    *,
    workflow_hash_override=None,
):
    source_sha=os.environ["GITHUB_SHA"]
    required_paths=list(REQUIRED_PROTOCOLS)+list(REQUIRED_PRODUCTION_WORKFLOWS)+[WORKFLOW]
    hashes={}
    for required_path in required_paths:
        payload=subprocess.run(
            ["git","-C",str(ROOT),"show",f"{source_sha}:{required_path}"],
            check=True,capture_output=True,timeout=120,
        ).stdout
        hashes[required_path]=digest(payload)
    if workflow_hash_override is not None:
        hashes[WORKFLOW]=workflow_hash_override
    manifest={
        "schema":"btc-predictive-vnext4r72-negative-e2e-manifest-v1",
        "source_commit_sha":source_sha,
        "paths_sha256":hashes,
        "all_protocols":list(REQUIRED_PROTOCOLS),
        "deployment_workflows":list(REQUIRED_PRODUCTION_WORKFLOWS),
        "evidence_branch":NEG_BRANCH,
    }
    schedule=make_event(1,None,{
        "type":"SCHEDULE_REGISTERED",
        "idempotency_key":"1h:schedule",
        "head":"1h",
        "start_utc":start.isoformat(),
        "deadline_minutes":10,
        "protocol_sha256":digest(protocol_path.read_bytes()),
        "source_commit_sha":source_sha,
        "trading_authority":False,
    })
    write_signed(events_dir,schedule)
    freeze=make_event(2,digest(canonical(schedule)),{
        "type":"CONFIG_FROZEN_PRESTART",
        "idempotency_key":"1h:freeze",
        "head":"1h",
        "start_utc":start.isoformat(),
        "manifest_sha256":digest(canonical(manifest)),
        "manifest":manifest,
        "trading_authority":False,
    })
    write_signed(events_dir,freeze)
    return schedule,freeze


def forecast_event(
    seq,previous,start,case_dir,
    *,
    published=None,
    head="1h",
    raw_sha_override=None,
):
    raw=RAW_ROOT/case_dir.name/"raw.json"
    raw.parent.mkdir(parents=True,exist_ok=True)
    raw.write_bytes(canonical({"source":"negative-e2e","slot":start.isoformat()}))
    slot=start.strftime("%Y%m%dT%H%M%SZ")
    return make_event(seq,previous,{
        "type":"FORECAST_ISSUED",
        "idempotency_key":"forecast:"+slot,
        "slot":slot,
        "head":head,
        "anchor_utc":start.isoformat(),
        "due_utc":(start+timedelta(seconds=60)).isoformat(),
        "published_at_utc":(
            published or (start+timedelta(seconds=1))
        ).isoformat(),
        "reference_price":100.0,
        "lower_price":99.0,
        "upper_price":101.0,
        "selected_model":"NEGATIVE_E2E_DUMMY",
        "class_distribution":{
            "lower_first":.25,"upper_first":.25,
            "neither":.50,"ambiguous_same_bar":0.0,
        },
        "components":{},
        "control":{
            "primary_distribution":{
                "lower_first":.25,"upper_first":.25,
                "neither":.50,"ambiguous_same_bar":0.0,
            },
            "volatility_bin":2,
        },
        "probability_status":"NEGATIVE_E2E_ONLY",
        "artifact_sha256":"a"*64,
        "baseline_sha256":"b"*64,
        "raw_path":str(raw.relative_to(ROOT)),
        "raw_sha256":(
            raw_sha_override
            if raw_sha_override is not None
            else digest(raw.read_bytes())
        ),
        "trading_authority":False,
    })


def expect_failure(name,case_dir,expected_fragment=None):
    try:
        result=run_admission(
            repo_root=str(ROOT),
            protocol_path=str((case_dir/"protocol.json").relative_to(ROOT)),
            events_dir=str((case_dir/"events").relative_to(ROOT)),
            current_tip=subprocess.run(
                ["git","rev-parse","HEAD"],
                cwd=ROOT,check=True,capture_output=True,text=True,
            ).stdout.strip(),
        )
    except Exception as ex:
        message=f"{type(ex).__name__}: {ex}"
        if expected_fragment and expected_fragment.lower() not in message.lower():
            raise AssertionError(
                f"{name}: wrong failure: {message}"
            ) from ex
        print(json.dumps({"attack":name,"rejected":True,"error":message}))
        return
    if result.get("admission_ready") is False and (
        expected_fragment is None
        or expected_fragment.lower() in str(result.get("status","")).lower()
    ):
        print(json.dumps({"attack":name,"rejected":True,"result":result}))
        return
    raise AssertionError(f"{name}: attack unexpectedly accepted: {result}")


def case_dir(name):
    d=BASE/name
    (d/"events").mkdir(parents=True,exist_ok=True)
    return d


def main():
    shutil.rmtree(BASE,ignore_errors=True)
    shutil.rmtree(RAW_ROOT,ignore_errors=True)
    BASE.mkdir()
    RAW_ROOT.mkdir(parents=True,exist_ok=True)
    subprocess.run(
        ["git","config","user.name","btc-predictive-r72-negative-e2e[bot]"],
        cwd=ROOT,check=True,
    )
    subprocess.run(
        ["git","config","user.email","btc-predictive-r72-negative-e2e[bot]@users.noreply.github.com"],
        cwd=ROOT,check=True,
    )
    subprocess.run(
        ["git","checkout","-B",NEG_BRANCH,os.environ["GITHUB_SHA"]],
        cwd=ROOT,check=True,capture_output=True,text=True,
    )
    subprocess.run(
        ["git","push","-u","origin","HEAD:"+NEG_BRANCH],
        cwd=ROOT,check=True,capture_output=True,text=True,
    )
    now=datetime.now(UTC)

    # 1. disabled protocol must block before scoring or verification.
    d=case_dir("disabled_protocol")
    p=protocol(now,enabled=False)
    write_protocol(d,p)
    expect_failure("disabled_protocol",d,"BLOCKED_PROTOCOL_ADMISSION_DISABLED")

    # 2. signed authority created after the declared start must be rejected.
    d=case_dir("late_authority")
    start=(datetime.now(UTC)-timedelta(seconds=5)).replace(microsecond=0)
    p=protocol(start)
    pp=write_protocol(d,p)
    authority_events(d/"events",start,pp)
    expect_failure("late_authority",d,"not in Rekor before start")

    # Build one common valid pre-start authority and reuse its exact signed bytes.
    common=case_dir("common")
    start=(datetime.now(UTC)+timedelta(seconds=50)).replace(microsecond=0)
    p=protocol(start)
    pp=write_protocol(common,p)
    authority_events(common/"events",start,pp)

    # 3. valid OIDC identity but workflow content mismatch against signed manifest.
    # Create it before the common start so the targeted failure is workflow binding,
    # not late pre-start authority.
    d=case_dir("workflow_manifest_mismatch")
    shutil.copy2(common/"protocol.json",d/"protocol.json")
    authority_events(
        d/"events",start,d/"protocol.json",
        workflow_hash_override="0"*64,
    )
    expect_failure(
        "workflow_manifest_mismatch",d,
        "workflow content differs from signed frozen manifest",
    )

    while datetime.now(UTC)<start+timedelta(seconds=1):
        time.sleep(.25)

    def prepare(name):
        d=case_dir(name)
        shutil.copy2(common/"protocol.json",d/"protocol.json")
        for n in ("00000001.json","00000001.sigstore.json",
                  "00000002.json","00000002.sigstore.json"):
            shutil.copy2(common/"events"/n,d/"events"/n)
        freeze=json.loads((d/"events"/"00000002.json").read_text())
        return d,freeze

    # 4. a signed event modified after signing must fail Cosign verification.
    d,freeze=prepare("signature_tamper")
    fc=forecast_event(3,digest(canonical(freeze)),start,d)
    path,bundle=write_signed(d/"events",fc)
    fc["reference_price"]=123.0
    path.write_bytes(canonical(fc))
    expect_failure("signature_tamper",d)

    # 5. raw bytes/hash are mandatory.
    d,freeze=prepare("raw_hash_mismatch")
    fc=forecast_event(
        3,digest(canonical(freeze)),start,d,
        raw_sha_override="f"*64,
    )
    write_signed(d/"events",fc)
    expect_failure("raw_hash_mismatch",d,"raw attachment hash mismatch")

    # 6. receipt must bind the exact forecast sequence and event hash.
    d,freeze=prepare("receipt_target_mismatch")
    fc=forecast_event(3,digest(canonical(freeze)),start,d)
    write_signed(d/"events",fc)
    slot=fc["slot"]
    receipt=make_event(4,digest(canonical(fc)),{
        "type":"DELIVERY_CONFIRMED",
        "idempotency_key":"delivery:forecast:"+slot,
        "head":"1h",
        "slot":slot,
        "target_sequence":999,
        "target_event_hash":"e"*64,
        "remote_commit_sha":"1"*40,
        "remote_confirmed_at_utc":(start+timedelta(seconds=2)).isoformat(),
        "deadline_utc":(start+timedelta(seconds=600)).isoformat(),
        "published_at_utc":(start+timedelta(seconds=2)).isoformat(),
        "trading_authority":False,
    })
    write_signed(d/"events",receipt)
    expect_failure(
        "receipt_target_mismatch",d,"receipt target_sequence mismatch"
    )

    # 7. forecast publication at/after the frozen deadline is invalid.
    d,freeze=prepare("late_forecast")
    fc=forecast_event(
        3,digest(canonical(freeze)),start,d,
        published=start+timedelta(seconds=601),
    )
    write_signed(d/"events",fc)
    expect_failure("late_forecast",d,"forecast published after deadline")

    # 8. outcome before due is invalid even when it is correctly signed.
    d,freeze=prepare("early_outcome")
    fc=forecast_event(3,digest(canonical(freeze)),start,d)
    write_signed(d/"events",fc)
    slot=fc["slot"]
    outcome=make_event(4,digest(canonical(fc)),{
        "type":"OUTCOME_RECORDED",
        "idempotency_key":"outcome:"+slot,
        "slot":slot,
        "head":"1h",
        "anchor_utc":start.isoformat(),
        "due_utc":(start+timedelta(seconds=60)).isoformat(),
        "published_at_utc":(start+timedelta(seconds=59)).isoformat(),
        "outcome_class":"NEITHER",
        "first_touch_time_utc":None,
        "lower_price":99.0,
        "upper_price":101.0,
        "raw_path":fc["raw_path"],
        "raw_sha256":fc["raw_sha256"],
        "trading_authority":False,
    })
    write_signed(d/"events",outcome)
    expect_failure("early_outcome",d,"outcome published before due")

    # 9. signed cross-head replay is rejected semantically before scoring.
    d,freeze=prepare("cross_head_replay")
    fc=forecast_event(
        3,digest(canonical(freeze)),start,d,head="4h"
    )
    slot=fc["slot"]
    fc["idempotency_key"]="forecast:"+slot
    write_signed(d/"events",fc)
    expect_failure("cross_head_replay",d,"event head mismatch")

    # 10. deleting a Sigstore bundle is fail-closed.
    d,freeze=prepare("missing_signature_bundle")
    fc=forecast_event(3,digest(canonical(freeze)),start,d)
    path,bundle=write_signed(d/"events",fc)
    bundle.unlink()
    expect_failure("missing_signature_bundle",d)

    # 11. Rekor inclusion proof is mandatory even for an otherwise valid bundle.
    d,freeze=prepare("corrupted_rekor_proof")
    fc=forecast_event(3,digest(canonical(freeze)),start,d)
    path,bundle=write_signed(d/"events",fc)
    obj=json.loads(bundle.read_text())
    entries=obj.get("verificationMaterial",{}).get("tlogEntries",[])
    if not entries:
        raise RuntimeError("negative E2E bundle unexpectedly lacks tlog entry")
    entries[0]["inclusionProof"]={}
    bundle.write_text(json.dumps(obj,separators=(",",":"),sort_keys=True))
    expect_failure("corrupted_rekor_proof",d)

    # Preserve every signed negative artifact for independent read-only replay.
    subprocess.run(["git","add","r71_negative_e2e","predictive_vnext4r71_1h_raw"],cwd=ROOT,check=True)
    subprocess.run(
        ["git","commit","-m","R7.2 preserve signed negative E2E artifacts"],
        cwd=ROOT,check=True,capture_output=True,text=True,
    )
    subprocess.run(
        ["git","push","origin","HEAD:"+NEG_BRANCH],
        cwd=ROOT,check=True,capture_output=True,text=True,
    )
    tip=subprocess.run(
        ["git","rev-parse","HEAD"],cwd=ROOT,check=True,capture_output=True,text=True,
    ).stdout.strip()
    print(json.dumps({
        "status":"R7_2_NEGATIVE_E2E_PASS",
        "attacks":11,
        "real_oidc_rekor":True,
        "preserved_branch":NEG_BRANCH,
        "preserved_tip":tip,
        "mandatory_admission_entrypoint":"predictive_vnext4r71/admission.py",
    },sort_keys=True))


if __name__=="__main__":
    main()
