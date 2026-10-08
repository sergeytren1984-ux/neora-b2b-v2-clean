"""Cryptographic evidence replay and canonical-row derivation for vNext5R3.

This module is the provenance boundary between the signed Git/Rekor journal and
the numerical prospective scorer.  It accepts no caller-supplied forecast rows.
Rows are derived only after full signature/Rekor/hash-chain/raw/publication
verification of an exact fetched evidence-branch snapshot.
"""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from predictive_vnext4r7.integrity import canonical, digest, git_bytes, parse_utc
from predictive_vnext4r71.crypto import make_blob_verifier
from predictive_vnext4r71.integrity import safe_repo_relative_path

UTC=timezone.utc
HEX40=re.compile(r"^[0-9a-f]{40}$")
RAW_CLASS_TO_ID={
    "LOWER_FIRST":0,
    "UPPER_FIRST":1,
    "NEITHER":2,
    "AMBIGUOUS_SAME_BAR":3,
}


@dataclass(frozen=True)
class VerifiedEvidence:
    rows: tuple[dict,...]
    governance: dict
    start_utc: str
    evidence_branch: str
    evidence_tip: str
    source_commit_sha: str


def _git(root:Path,*args,text=True):
    return subprocess.run(
        ["git","-C",str(root),*args],
        check=True,capture_output=True,text=text,timeout=180
    ).stdout


def _is_ancestor(root:Path,ancestor:str,tip:str):
    subprocess.run(
        ["git","-C",str(root),"merge-base","--is-ancestor",ancestor,tip],
        check=True,capture_output=True,timeout=120
    )


def _path_addition_commit(root:Path,tip:str,path:str)->str:
    out=_git(
        root,"log","--diff-filter=A","--format=%H","--reverse",
        tip,"--",path
    ).strip().splitlines()
    if len(out)!=1:
        raise ValueError("evidence path must have exactly one addition commit: "+path)
    return out[0]


def _event_files(events_dir:Path):
    return sorted(
        p for p in events_dir.glob("*.json")
        if len(p.stem)==8 and p.stem.isdigit()
    )


def _protocol_duration(cfg:dict,key_minutes:str,key_seconds:str)->timedelta:
    if key_seconds in cfg:
        value=float(cfg[key_seconds])
        if value<=0:
            raise ValueError("duration must be positive")
        return timedelta(seconds=value)
    value=float(cfg[key_minutes])
    if value<=0:
        raise ValueError("duration must be positive")
    return timedelta(minutes=value)


def _load_events(events_dir:Path):
    files=_event_files(events_dir)
    if not files:
        raise ValueError("evidence journal empty")
    events=[]
    previous=None
    for i,path in enumerate(files,1):
        raw=path.read_bytes()
        event=json.loads(raw)
        if raw!=canonical(event):
            raise ValueError("non-canonical event bytes")
        if event.get("schema")!="btc-predictive-vnext5r3-evidence-event-v1":
            raise ValueError("unexpected evidence event schema")
        if type(event.get("sequence")) is not int or event["sequence"]!=i:
            raise ValueError("event sequence gap")
        if event.get("previous_hash")!=previous:
            raise ValueError("event hash chain broken")
        if not isinstance(event.get("idempotency_key"),str):
            raise ValueError("event idempotency key missing")
        events.append(event)
        previous=digest(raw)
    keys=[e["idempotency_key"] for e in events]
    if len(keys)!=len(set(keys)):
        raise ValueError("duplicate evidence idempotency key")
    return events,files


def _verify_source_manifest(root:Path,manifest:dict,source_sha:str):
    if manifest.get("source_commit_sha")!=source_sha:
        raise ValueError("signed manifest source mismatch")
    paths=manifest.get("paths_sha256")
    if not isinstance(paths,dict) or not paths:
        raise ValueError("signed manifest static paths missing")
    for path,want in paths.items():
        if not isinstance(path,str) or not isinstance(want,str) or len(want)!=64:
            raise ValueError("invalid static path binding")
        got=digest(git_bytes(root,source_sha,path))
        if got!=want:
            raise ValueError("static source path hash mismatch: "+path)


def _verify_raw_publication(
    root:Path,
    tip:str,
    event:dict,
    event_path:Path,
    required_prefix:str,
):
    raw_path=event.get("raw_path")
    raw_sha=event.get("raw_sha256")
    if not isinstance(raw_sha,str) or len(raw_sha)!=64:
        raise ValueError("raw attachment metadata missing")
    local,rel=safe_repo_relative_path(root,raw_path)
    if not rel.startswith(required_prefix):
        raise ValueError("raw attachment outside frozen prefix")
    if not local.exists() or digest(local.read_bytes())!=raw_sha:
        raise ValueError("raw attachment hash mismatch")
    event_rel=str(event_path.resolve().relative_to(root.resolve()))
    event_commit=_path_addition_commit(root,tip,event_rel)
    raw_commit=_path_addition_commit(root,tip,rel)
    if raw_commit!=event_commit:
        raise ValueError("raw first publication differs from event publication commit")
    if git_bytes(root,event_commit,event_rel)!=canonical(event):
        raise ValueError("publication commit lacks exact event")
    if git_bytes(root,event_commit,rel)!=local.read_bytes():
        raise ValueError("publication commit lacks exact raw bytes")
    _is_ancestor(root,event_commit,tip)
    return event_commit


def _target_fields(event:dict):
    if event.get("query_type")!="CANONICAL":
        raise ValueError("non-canonical evidence cannot enter primary admission")
    if event.get("target_id")!="CANONICAL_SIGMA_1_1_V1":
        raise ValueError("canonical target id mismatch")
    for key in ("lower_sigma","upper_sigma"):
        value=event.get(key)
        if isinstance(value,bool) or not isinstance(value,(int,float)):
            raise ValueError("canonical sigma must be numeric")
        if abs(float(value)-1.0)>1e-12:
            raise ValueError("canonical sigma mismatch")


def _prediction_vector(value):
    if not isinstance(value,list) or len(value)!=4:
        raise ValueError("signed prediction must contain four probabilities")
    out=[]
    for x in value:
        if isinstance(x,bool) or not isinstance(x,(int,float)):
            raise ValueError("signed prediction probability invalid")
        v=float(x)
        if not (v>=0.0) or not (v<1e309):
            raise ValueError("signed prediction probability invalid")
        out.append(v)
    if abs(sum(out)-1.0)>1e-8:
        raise ValueError("signed prediction probabilities do not sum to one")
    return out


def verify_evidence_snapshot(
    *,
    root:Path,
    protocol_path:str,
    events_dir:str,
    current_tip:str,
    expected_branch:str,
    allow_e2e_short_horizon:bool=False,
)->VerifiedEvidence:
    root=Path(root).resolve()
    if not HEX40.fullmatch(str(current_tip)):
        raise ValueError("invalid evidence tip")

    protocol_file=root/protocol_path
    protocol_bytes=protocol_file.read_bytes()
    protocol=json.loads(protocol_bytes)
    if protocol_bytes!=canonical(protocol):
        raise ValueError("protocol is not canonical")
    mode=protocol.get("mode","PROSPECTIVE")
    if mode!="PROSPECTIVE" and not (allow_e2e_short_horizon and mode=="E2E"):
        raise ValueError("non-prospective evidence protocol forbidden")

    head=protocol.get("head")
    if head not in {"1h","4h","24h"}:
        raise ValueError("invalid protocol head")
    cfg=protocol.get("head_config")
    if not isinstance(cfg,dict):
        raise ValueError("head config missing")
    horizon=_protocol_duration(cfg,"horizon_minutes","horizon_seconds")
    deadline=_protocol_duration(
        cfg,"forecast_deadline_minutes","forecast_deadline_seconds"
    )
    candidates=cfg.get("candidates")
    artifacts=cfg.get("artifact_sha256")
    if not isinstance(candidates,list) or not candidates:
        raise ValueError("candidate set missing")
    if not isinstance(artifacts,dict) or set(artifacts)!=set(candidates):
        raise ValueError("artifact binding incomplete")

    events,files=_load_events(root/events_dir)
    schedule=[e for e in events if e.get("type")=="SCHEDULE_REGISTERED"]
    freezes=[e for e in events if e.get("type")=="CONFIG_FROZEN_PRESTART"]
    if len(schedule)!=1 or len(freezes)!=1:
        raise ValueError("exactly one schedule and freeze event required")
    schedule=schedule[0]; freeze=freezes[0]
    if schedule["sequence"]!=1 or freeze["sequence"]!=2:
        raise ValueError("schedule/freeze must be first two events")
    if schedule.get("head")!=head or freeze.get("head")!=head:
        raise ValueError("authority head mismatch")

    if schedule.get("evidence_branch")!=expected_branch:
        raise ValueError("schedule evidence branch mismatch")
    if freeze.get("evidence_branch")!=expected_branch:
        raise ValueError("freeze evidence branch mismatch")
    if schedule.get("protocol_sha256")!=digest(protocol_bytes):
        raise ValueError("schedule protocol hash mismatch")

    source_sha=str(schedule.get("source_commit_sha","")).lower()
    if not HEX40.fullmatch(source_sha):
        raise ValueError("invalid source commit")
    if freeze.get("source_commit_sha")!=source_sha:
        raise ValueError("freeze source commit mismatch")
    if schedule.get("workflow_commit")!=source_sha:
        raise ValueError("schedule workflow commit must equal source commit")
    _is_ancestor(root,source_sha,current_tip)

    start=parse_utc(schedule.get("start_utc"))
    if parse_utc(freeze.get("start_utc"))!=start:
        raise ValueError("schedule/freeze start mismatch")
    source_ref=schedule.get("source_ref")
    trigger=schedule.get("workflow_trigger")
    if not isinstance(source_ref,str) or not source_ref.startswith("refs/heads/"):
        raise ValueError("invalid signed source ref")
    if trigger not in {"workflow_dispatch","schedule"}:
        raise ValueError("invalid signed workflow trigger")
    if freeze.get("source_ref")!=source_ref or freeze.get("workflow_trigger")!=trigger:
        raise ValueError("freeze signing authority mismatch")

    manifest=freeze.get("manifest")
    if not isinstance(manifest,dict):
        raise ValueError("signed manifest missing")
    if freeze.get("manifest_sha256")!=digest(canonical(manifest)):
        raise ValueError("signed manifest hash mismatch")
    if manifest.get("evidence_branch")!=expected_branch:
        raise ValueError("manifest evidence branch mismatch")
    if manifest.get("protocol_sha256")!=digest(protocol_bytes):
        raise ValueError("manifest protocol hash mismatch")
    if manifest.get("source_ref")!=source_ref:
        raise ValueError("manifest source ref mismatch")
    if manifest.get("workflow_trigger")!=trigger:
        raise ValueError("manifest trigger mismatch")
    _verify_source_manifest(root,manifest,source_sha)

    repository=protocol.get("repository")
    workflow_path=protocol.get("workflow_path")
    if repository!="sergeytren1984-ux/neora-b2b-v2-clean":
        raise ValueError("unexpected repository authority")
    if not isinstance(workflow_path,str) or not workflow_path:
        raise ValueError("workflow path missing")
    if workflow_path not in manifest.get("paths_sha256",{}):
        raise ValueError("workflow absent from signed manifest")

    verify_blob=make_blob_verifier(
        repository=repository,
        workflow_path=workflow_path,
        ref=source_ref,
        trigger=trigger,
        repo_root=root,
    )

    rekor={}
    for event,path in zip(events,files):
        if event.get("workflow_commit")!=source_sha:
            raise ValueError("event workflow commit differs from frozen source")
        # Bind workflow bytes independently at the signing commit.
        got=digest(git_bytes(root,source_sha,workflow_path))
        want=manifest["paths_sha256"][workflow_path]
        if got!=want:
            raise ValueError("event workflow content differs from signed manifest")
        bundle=path.with_suffix(".sigstore.json")
        if not bundle.exists():
            raise ValueError("event signature bundle missing")
        rekor[event["sequence"]]=verify_blob(path,bundle,event)

    if rekor[schedule["sequence"]]>=start or rekor[freeze["sequence"]]>=start:
        raise ValueError("schedule/freeze not in Rekor before start")

    forecasts={}
    receipts={}
    outcomes={}
    raw_prefix=f"predictive_vnext5_{head}_raw/"
    for event,path in zip(events,files):
        et=event.get("type")
        if et in {"SCHEDULE_REGISTERED","CONFIG_FROZEN_PRESTART"}:
            continue
        if event.get("head")!=head:
            raise ValueError("live evidence head mismatch")
        slot=event.get("slot")
        if not isinstance(slot,str):
            raise ValueError("live evidence slot missing")
        if et=="FORECAST_ISSUED":
            if slot in forecasts:
                raise ValueError("duplicate forecast slot")
            _target_fields(event)
            anchor=parse_utc(event.get("anchor_utc"))
            due=parse_utc(event.get("due_utc"))
            if due!=anchor+horizon:
                raise ValueError("forecast horizon mismatch")
            if parse_utc(event.get("published_at_utc"))<anchor:
                raise ValueError("forecast published before anchor")
            if rekor[event["sequence"]]<anchor:
                raise ValueError("forecast Rekor time before anchor")
            if rekor[event["sequence"]]>=anchor+deadline:
                raise ValueError("forecast Rekor time late")
            if event.get("artifact_sha256")!=artifacts:
                raise ValueError("forecast artifact binding mismatch")
            predictions=event.get("predictions")
            if not isinstance(predictions,dict) or set(predictions)!=set(candidates):
                raise ValueError("forecast candidate predictions incomplete")
            for candidate in candidates:
                _prediction_vector(predictions[candidate])
            vol=event.get("volatility")
            if isinstance(vol,bool) or not isinstance(vol,(int,float)) or not float(vol)>0:
                raise ValueError("forecast volatility invalid")
            event_commit=_verify_raw_publication(
                root,current_tip,event,path,raw_prefix
            )
            forecasts[slot]=(event,path,event_commit)
        elif et=="DELIVERY_CONFIRMED":
            if slot in receipts:
                raise ValueError("duplicate delivery receipt slot")
            receipts[slot]=(event,path)
        elif et=="OUTCOME_RECORDED":
            if slot in outcomes:
                raise ValueError("duplicate outcome slot")
            _target_fields(event)
            anchor=parse_utc(event.get("anchor_utc"))
            due=parse_utc(event.get("due_utc"))
            if due!=anchor+horizon:
                raise ValueError("outcome horizon mismatch")
            if parse_utc(event.get("published_at_utc"))<due:
                raise ValueError("outcome published before due")
            if rekor[event["sequence"]]<due:
                raise ValueError("outcome Rekor time before due")
            if event.get("outcome_class") not in RAW_CLASS_TO_ID:
                raise ValueError("invalid signed outcome class")
            _verify_raw_publication(root,current_tip,event,path,raw_prefix)
            outcomes[slot]=(event,path)
        elif et=="SLOT_MISSED":
            continue
        else:
            raise ValueError("unsupported evidence event type: "+str(et))

    rows=[]
    for slot,(forecast,fpath,forecast_commit) in forecasts.items():
        receipt_pair=receipts.get(slot)
        if receipt_pair is None:
            raise ValueError("forecast missing delivery receipt: "+slot)
        receipt,rpath=receipt_pair
        anchor=parse_utc(forecast["anchor_utc"])
        if receipt.get("target_sequence")!=forecast["sequence"]:
            raise ValueError("delivery target sequence mismatch")
        if receipt.get("target_event_hash")!=digest(canonical(forecast)):
            raise ValueError("delivery target event hash mismatch")
        if receipt.get("remote_commit_sha")!=forecast_commit:
            raise ValueError("delivery receipt does not name forecast publication commit")
        if rekor[receipt["sequence"]]>=anchor+deadline:
            raise ValueError("delivery receipt Rekor time late")
        if rekor[receipt["sequence"]]<anchor:
            raise ValueError("delivery receipt Rekor time before anchor")
        event_rel=str(fpath.resolve().relative_to(root.resolve()))
        if git_bytes(root,forecast_commit,event_rel)!=canonical(forecast):
            raise ValueError("receipt publication commit lacks exact forecast")

        outcome_pair=outcomes.get(slot)
        if outcome_pair is None:
            continue
        outcome,_=outcome_pair
        if outcome.get("anchor_utc")!=forecast.get("anchor_utc"):
            raise ValueError("outcome/forecast anchor mismatch")
        if outcome.get("due_utc")!=forecast.get("due_utc"):
            raise ValueError("outcome/forecast due mismatch")
        for key in ("query_type","target_id","lower_sigma","upper_sigma"):
            if outcome.get(key)!=forecast.get(key):
                raise ValueError("outcome/forecast target mismatch")

        issued=max(
            rekor[forecast["sequence"]],
            rekor[receipt["sequence"]],
        )
        recorded=rekor[outcome["sequence"]]
        for candidate in candidates:
            rows.append({
                "schema":"btc-predictive-vnext5r2-canonical-row-v1",
                "query_type":"CANONICAL",
                "target_id":"CANONICAL_SIGMA_1_1_V1",
                "lower_sigma":1.0,
                "upper_sigma":1.0,
                "head":head,
                "candidate_id":candidate,
                "anchor_utc":forecast["anchor_utc"],
                "forecast_issued_at_utc":issued.isoformat(),
                "due_utc":forecast["due_utc"],
                "outcome_recorded_at_utc":recorded.isoformat(),
                "prediction_raw":_prediction_vector(
                    forecast["predictions"][candidate]
                ),
                "outcome_class":RAW_CLASS_TO_ID[outcome["outcome_class"]],
                "volatility":float(forecast["volatility"]),
            })

    governance={
        "schema":"btc-predictive-vnext5r3-evidence-governance-v1",
        "full_cryptographic_replay":True,
        "all_event_signatures_verified":True,
        "all_rekor_inclusion_proofs_verified":True,
        "event_hash_chain_verified":True,
        "workflow_content_binding_verified":True,
        "static_source_manifest_verified":True,
        "raw_hashes_verified":True,
        "raw_remote_publication_verified":True,
        "forecast_delivery_receipt_verified":True,
        "exact_evidence_tip_bound":current_tip,
        "source_commit_sha":source_sha,
        "source_ref":source_ref,
        "protocol_sha256":digest(protocol_bytes),
        "signed_manifest_sha256":digest(canonical(manifest)),
        "verified_event_count":len(events),
        "derived_row_count":len(rows),
        "row_time_authority":"REKOR_INTEGRATED_TIME",
        "arbitrary_jsonl_input_used":False,
        "trading_authority":False,
    }
    return VerifiedEvidence(
        rows=tuple(rows),
        governance=governance,
        start_utc=start.isoformat(),
        evidence_branch=expected_branch,
        evidence_tip=current_tip,
        source_commit_sha=source_sha,
    )
