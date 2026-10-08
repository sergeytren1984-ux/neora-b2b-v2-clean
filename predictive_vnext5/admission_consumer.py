"""Authenticated read-only consumer boundary for vNext5R4.2.

The consumer no longer accepts a caller-supplied decision object.  It obtains
the decision only by invoking the trusted prospective admission launcher with
an approved source SHA supplied outside the evidence journal, then rechecks the
remote evidence tip immediately before returning a current snapshot.
"""
from __future__ import annotations

import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from predictive_vnext4r7.integrity import canonical, digest
from predictive_vnext5.prospective_admission import run_verified_admission

HEX40=re.compile(r"^[0-9a-f]{40}$")
UTC=timezone.utc
DECISION_SCHEMA="btc-predictive-vnext5r42-verified-admission-v1"
CONSUMER_SCHEMA="btc-predictive-vnext5r42-current-snapshot-v1"


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


def _validate_authenticated_decision(
    decision:dict,
    *,
    expected_head:str,
    expected_cutoff_utc:str,
    approved_source_sha:str,
    expected_evidence_branch:str,
):
    if type(decision) is not dict or decision.get("schema")!=DECISION_SCHEMA:
        raise ValueError("authenticated admission decision schema mismatch")
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
        "trusted_source_bootstrap_verified",
        "outcome_barriers_bound_to_forecast",
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
    trusted=str(governance.get("trusted_approved_source_sha","")).lower()
    if branch!=expected_evidence_branch:
        raise ValueError("consumer evidence branch mismatch")
    if not HEX40.fullmatch(tip):
        raise ValueError("invalid decision evidence tip")
    if source!=str(approved_source_sha).lower():
        raise ValueError("consumer verified source mismatch")
    if trusted!=str(approved_source_sha).lower():
        raise ValueError("consumer trusted source mismatch")
    return governance


def consume_verified_admission(
    *,
    repo_root:str,
    approved_source_sha:str,
    head:str,
    evidence_branch:str,
    protocol_path:str,
    cutoff_utc:str,
    model_root:str,
):
    """Run authoritative verification and consume only that in-memory result."""
    decision=run_verified_admission(
        repo_root=repo_root,
        approved_source_sha=approved_source_sha,
        head=head,
        evidence_branch=evidence_branch,
        protocol_path=protocol_path,
        cutoff_utc=cutoff_utc,
        model_root=model_root,
    )
    governance=_validate_authenticated_decision(
        decision,
        expected_head=head,
        expected_cutoff_utc=cutoff_utc,
        approved_source_sha=approved_source_sha,
        expected_evidence_branch=evidence_branch,
    )

    root=Path(repo_root).resolve()
    current=_remote_tip(root,evidence_branch)
    if current!=governance["evidence_tip"]:
        raise ValueError("admission decision is stale at consumer boundary")

    return {
        "schema":CONSUMER_SCHEMA,
        "head":head,
        "cutoff_utc":_utc(cutoff_utc).isoformat(),
        "evidence_branch":evidence_branch,
        "evidence_tip":governance["evidence_tip"],
        "source_commit_sha":governance["verified_source_commit_sha"],
        "decision_sha256":digest(canonical(decision)),
        "snapshot_current":True,
        "admission_ready":bool(decision.get("admission_ready")),
        "selected_candidate":decision.get("selected_candidate"),
        "prospective_skill_proven":False,
        "trading_authority":False,
    }


def main():
    raise SystemExit(
        "consumer is a library boundary; use consume_verified_admission() "
        "with an externally approved source SHA"
    )


if __name__=="__main__":
    main()
