"""Read-only consumer-side snapshot guard for vNext5R4.1.

A verified admission decision is a statement about one exact evidence snapshot.
This module is the mandatory boundary before any caller may treat that decision
as current.  It never authorizes trading or performs side effects.
"""
from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from predictive_vnext4r7.integrity import canonical, digest

HEX40=re.compile(r"^[0-9a-f]{40}$")
UTC=timezone.utc
DECISION_SCHEMA="btc-predictive-vnext5r41-verified-admission-v1"
CONSUMER_SCHEMA="btc-predictive-vnext5r41-current-snapshot-v1"


def _git(root:Path,*args):
    return subprocess.run(
        ["git","-C",str(root),*args],
        check=True,capture_output=True,text=True,timeout=180
    ).stdout.strip()


def _remote_tip(root:Path,branch:str)->str:
    subprocess.run(
        ["git","-C",str(root),"fetch","origin",branch],
        check=True,capture_output=True,timeout=180
    )
    return _git(root,"rev-parse","origin/"+branch)


def _utc(value):
    if type(value) is not str:
        raise ValueError("cutoff must be ISO-8601 string")
    dt=datetime.fromisoformat(value.replace("Z","+00:00"))
    if dt.tzinfo is None:
        raise ValueError("cutoff must be timezone aware")
    return dt.astimezone(UTC)


def assert_current_snapshot(
    decision:dict,
    *,
    repo_root:str,
    expected_head:str,
    expected_cutoff_utc:str,
    expected_source_sha:str|None=None,
    expected_evidence_branch:str|None=None,
):
    """Fail closed unless a verified decision is still current at consumption.

    The returned object is read-only decision support.  It deliberately keeps
    trading_authority=False even when admission_ready=True.
    """
    if type(decision) is not dict:
        raise ValueError("verified admission decision must be an object")
    if decision.get("schema")!=DECISION_SCHEMA:
        raise ValueError("unverified or unsupported admission decision schema")
    if decision.get("head")!=expected_head:
        raise ValueError("decision head mismatch")
    if _utc(decision.get("cutoff_utc"))!=_utc(expected_cutoff_utc):
        raise ValueError("decision cutoff mismatch")
    if decision.get("trading_authority") is not False:
        raise ValueError("trading authority must remain false")
    if decision.get("prospective_skill_proven") is not False:
        raise ValueError("consumer cannot promote skill authority")

    governance=decision.get("governance")
    if type(governance) is not dict:
        raise ValueError("verified admission governance missing")
    required_true=(
        "full_cryptographic_replay",
        "all_event_signatures_verified",
        "all_rekor_inclusion_proofs_verified",
        "event_hash_chain_verified",
        "workflow_content_binding_verified",
        "static_source_manifest_verified",
        "execution_contract_verified",
        "executed_source_bytes_verified",
        "raw_hashes_verified",
        "raw_remote_publication_verified",
        "forecast_delivery_receipt_verified",
        "canonical_rows_derived_only_from_verified_journal",
        "standalone_jsonl_admission_forbidden",
        "remote_tip_revalidated_after_scoring",
        "numerical_provenance_replayed",
    )
    for key in required_true:
        if governance.get(key) is not True:
            raise ValueError("consumer governance requirement failed: "+key)
    if governance.get("protocol_mode")!="PROSPECTIVE":
        raise ValueError("consumer accepts prospective protocol only")
    if governance.get("admission_eligible") is not True:
        raise ValueError("snapshot is not admission eligible")

    branch=governance.get("evidence_branch")
    tip=str(governance.get("evidence_tip","")).lower()
    source=str(governance.get("verified_source_commit_sha","")).lower()
    if not isinstance(branch,str) or not branch:
        raise ValueError("evidence branch missing from decision")
    if not HEX40.fullmatch(tip):
        raise ValueError("invalid decision evidence tip")
    if not HEX40.fullmatch(source):
        raise ValueError("invalid decision source commit")
    if expected_evidence_branch is not None and branch!=expected_evidence_branch:
        raise ValueError("consumer evidence branch mismatch")
    if expected_source_sha is not None and source!=str(expected_source_sha).lower():
        raise ValueError("consumer source commit mismatch")

    root=Path(repo_root).resolve()
    current=_remote_tip(root,branch)
    if current!=tip:
        raise ValueError("admission decision is stale at consumer boundary")

    return {
        "schema":CONSUMER_SCHEMA,
        "head":expected_head,
        "cutoff_utc":_utc(expected_cutoff_utc).isoformat(),
        "evidence_branch":branch,
        "evidence_tip":tip,
        "source_commit_sha":source,
        "decision_sha256":digest(canonical(decision)),
        "snapshot_current":True,
        "admission_ready":bool(decision.get("admission_ready")),
        "selected_candidate":decision.get("selected_candidate"),
        "prospective_skill_proven":False,
        "trading_authority":False,
    }


def main():
    raise SystemExit(
        "consumer guard is a library boundary; pass an in-memory verified "
        "admission decision from prospective_admission.py"
    )


if __name__=="__main__":
    main()
