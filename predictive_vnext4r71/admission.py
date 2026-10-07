"""Single mandatory admission entrypoint for BTC Predictive vNext4R7.1.

No numerical scoring function is allowed to authorize admission. This module first
performs a full cryptographic and semantic replay of the evidence journal and only
then may promote already-computed statistical gates to admission_ready=true.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from predictive_vnext4r7.integrity import (
    canonical,
    digest,
    parse_utc,
    verify_event_workflow_against_manifest,
)
from predictive_vnext4r7.scorecard_core import score_from_events
from predictive_vnext4r71.checkpoint import event_files, verify_checkpoint
from predictive_vnext4r71.anchor import verify_latest_anchor
from predictive_vnext4r71.crypto import make_blob_verifier
from predictive_vnext4r71.integrity import (
    validate_event_collection,
    verify_raw_attachments,
    verify_all_workflow_bindings,
)

UTC = timezone.utc


def _git_bytes(root: Path, commit: str, path: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(root), "show", f"{commit}:{path}"],
        check=True,
        capture_output=True,
        timeout=180,
    ).stdout


def _is_ancestor(root: Path, ancestor: str, tip: str) -> None:
    subprocess.run(
        ["git", "-C", str(root), "merge-base", "--is-ancestor", ancestor, tip],
        check=True,
        capture_output=True,
        timeout=180,
    )


def _verify_manifest_source(root: Path, manifest: dict, workflow_paths: set[str]):
    source = manifest.get("source_commit_sha")
    if not isinstance(source, str) or len(source) != 40:
        raise ValueError("manifest source commit invalid")
    for path, want in manifest.get("paths_sha256", {}).items():
        if path in workflow_paths:
            continue
        got = digest(_git_bytes(root, source, path))
        if got != want:
            raise ValueError("manifest static source mismatch: " + path)


def _full_replay(
    *,
    root: Path,
    events_dir: Path,
    head: str,
    horizon: timedelta,
    issuance_deadline: timedelta,
    start_utc: datetime,
    forecast_workflow: str,
    outcome_workflow: str,
    verify_forecast_blob,
    verify_outcome_blob,
):
    files = event_files(events_dir)
    events = []
    rekor = {}
    previous = None

    for i, path in enumerate(files, 1):
        raw = path.read_bytes()
        event = json.loads(raw)
        if raw != canonical(event):
            raise ValueError("non-canonical event")
        if int(event.get("sequence", -1)) != i:
            raise ValueError("event sequence gap")
        if event.get("previous_hash") != previous:
            raise ValueError("event hash chain broken")
        verify = (
            verify_outcome_blob
            if event.get("type") == "OUTCOME_RECORDED"
            else verify_forecast_blob
        )
        rekor[i] = verify(path, path.with_suffix(".sigstore.json"), event)
        events.append(event)
        previous = digest(raw)

    relation = validate_event_collection(
        events,
        head=head,
        horizon=horizon,
        issuance_deadline=issuance_deadline,
    )
    schedule = relation["schedule"]
    freeze = relation["freeze"]
    if rekor[int(schedule["sequence"])] >= start_utc:
        raise ValueError("schedule not in Rekor before start")
    if rekor[int(freeze["sequence"])] >= start_utc:
        raise ValueError("freeze not in Rekor before start")
    if parse_utc(schedule.get("start_utc")) != start_utc:
        raise ValueError("schedule start mismatch")
    if parse_utc(freeze.get("start_utc")) != start_utc:
        raise ValueError("freeze start mismatch")

    manifest = freeze.get("manifest")
    if not isinstance(manifest, dict):
        raise ValueError("signed manifest missing")
    if digest(canonical(manifest)) != freeze.get("manifest_sha256"):
        raise ValueError("signed manifest hash mismatch")
    if schedule.get("source_commit_sha") != manifest.get("source_commit_sha"):
        raise ValueError("schedule/freeze source mismatch")

    verify_all_workflow_bindings(
        root,
        events,
        manifest,
        forecast_workflow=forecast_workflow,
        outcome_workflow=outcome_workflow,
    )

    deployment_workflows = set(
        manifest.get("deployment_workflows")
        or [forecast_workflow, outcome_workflow]
    )
    _verify_manifest_source(
        root, manifest, deployment_workflows
    )
    return events, rekor, manifest, relation


def _verify_governance(
    *,
    root: Path,
    events: list[dict],
    rekor: dict,
    relation: dict,
    protocol: dict,
    protocol_path: str,
    events_dir: Path,
    current_tip: str,
    issuance_deadline: timedelta,
):
    schedule = relation["schedule"]
    protocol_bytes = (root / protocol_path).read_bytes()
    if schedule.get("protocol_sha256") != digest(protocol_bytes):
        raise ValueError("schedule protocol hash mismatch")

    forecasts = {
        e["slot"]: e for e in events if e.get("type") == "FORECAST_ISSUED"
    }
    receipts = {
        e["slot"]: e for e in events if e.get("type") == "DELIVERY_CONFIRMED"
    }
    outcomes = {
        e["slot"]: e for e in events if e.get("type") == "OUTCOME_RECORDED"
    }

    verify_raw_attachments(root, events)

    for slot, forecast in forecasts.items():
        anchor = parse_utc(forecast["anchor_utc"])
        deadline = anchor + issuance_deadline
        if rekor[int(forecast["sequence"])] >= deadline:
            raise ValueError("forecast Rekor time late: " + slot)
        if forecast.get("artifact_sha256") != protocol.get("artifact_sha256"):
            raise ValueError("forecast artifact hash mismatch: " + slot)
        if forecast.get("baseline_sha256") != protocol.get("baseline_sha256"):
            raise ValueError("forecast baseline hash mismatch: " + slot)

        receipt = receipts.get(slot)
        if receipt is None:
            continue
        if rekor[int(receipt["sequence"])] >= deadline:
            raise ValueError("receipt Rekor time late: " + slot)
        commit = receipt.get("remote_commit_sha")
        if not isinstance(commit, str) or len(commit) != 40:
            raise ValueError("receipt remote commit invalid: " + slot)
        event_path = (
            str(events_dir.resolve().relative_to(root.resolve()))
            + f"/{int(forecast['sequence']):08d}.json"
        )
        if _git_bytes(root, commit, event_path) != canonical(forecast):
            raise ValueError("receipt commit lacks exact forecast: " + slot)
        _is_ancestor(root, commit, current_tip)

    for slot, outcome in outcomes.items():
        due = parse_utc(outcome["due_utc"])
        if rekor[int(outcome["sequence"])] < due:
            raise ValueError("outcome Rekor time before due: " + slot)

    return {
        "full_cryptographic_replay": True,
        "all_event_signatures_verified": True,
        "all_rekor_inclusion_proofs_verified": True,
        "workflow_content_binding_verified": True,
        "raw_hashes_verified": True,
        "receipt_forecast_exact_binding_verified": True,
        "remote_commit_ancestry_verified": True,
        "event_count": len(events),
    }


def run_admission(
    *,
    repo_root: str,
    protocol_path: str,
    events_dir: str,
    current_tip: str | None = None,
):
    root = Path(repo_root).resolve()
    protocol = json.loads((root / protocol_path).read_text())

    # The signed protocol is authoritative. The public API intentionally has no
    # parameters for verification callbacks, start, horizon, deadline, ref or
    # trigger that could override the frozen contract.
    if protocol.get("admission_enabled") is not True:
        return {
            "schema": "btc-predictive-vnext4r71-admission-v1",
            "head": protocol.get("head"),
            "admission_ready": False,
            "status": "BLOCKED_PROTOCOL_ADMISSION_DISABLED",
            "trading_authority": False,
        }

    head = protocol.get("head")
    if head not in {"1h", "4h", "24h"}:
        raise ValueError("protocol head invalid")
    if not protocol.get("start_utc"):
        raise ValueError("protocol start missing")
    start_utc = parse_utc(protocol["start_utc"])

    target = protocol.get("target", {})
    if "horizon_seconds" in target:
        horizon = timedelta(seconds=float(target["horizon_seconds"]))
    elif "horizon_minutes" in target:
        horizon = timedelta(minutes=float(target["horizon_minutes"]))
    else:
        raise ValueError("protocol horizon missing")

    if "issuance_deadline_seconds" in protocol:
        issuance_deadline = timedelta(
            seconds=float(protocol["issuance_deadline_seconds"])
        )
    elif "issuance_deadline_minutes" in protocol:
        issuance_deadline = timedelta(
            minutes=float(protocol["issuance_deadline_minutes"])
        )
    else:
        raise ValueError("protocol issuance deadline missing")

    workflows = protocol.get("workflows", {})
    forecast_workflow = workflows.get("forecast")
    outcome_workflow = workflows.get("outcome")
    if not isinstance(forecast_workflow, str) or not forecast_workflow:
        raise ValueError("protocol forecast workflow missing")
    if not isinstance(outcome_workflow, str) or not outcome_workflow:
        raise ValueError("protocol outcome workflow missing")

    binding = protocol.get("event_signature_binding", {})
    repository = binding.get("github_workflow_repository")
    expected_ref = binding.get("github_workflow_ref")
    expected_trigger = binding.get("github_workflow_trigger")
    if not all(
        isinstance(x, str) and x
        for x in (repository, expected_ref, expected_trigger)
    ):
        raise ValueError("protocol signature binding incomplete")

    if current_tip is None:
        current_tip = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        ).stdout.strip()

    verify_forecast_blob = make_blob_verifier(
        repository=repository,
        workflow_path=forecast_workflow,
        ref=expected_ref,
        trigger=expected_trigger,
        repo_root=root,
    )
    verify_outcome_blob = make_blob_verifier(
        repository=repository,
        workflow_path=outcome_workflow,
        ref=expected_ref,
        trigger=expected_trigger,
        repo_root=root,
    )

    events, rekor, manifest, relation = _full_replay(
        root=root,
        events_dir=root / events_dir,
        head=head,
        horizon=horizon,
        issuance_deadline=issuance_deadline,
        start_utc=start_utc,
        forecast_workflow=forecast_workflow,
        outcome_workflow=outcome_workflow,
        verify_forecast_blob=verify_forecast_blob,
        verify_outcome_blob=verify_outcome_blob,
    )
    schedule = relation["schedule"]
    if int(schedule.get("deadline_minutes", -1)) != int(
        issuance_deadline.total_seconds() // 60
    ):
        raise ValueError("schedule deadline differs from signed protocol")
    if "issuance_deadline_minutes" in protocol and int(
        protocol["issuance_deadline_minutes"]
    ) != int(issuance_deadline.total_seconds() // 60):
        raise ValueError("protocol deadline normalization mismatch")

    governance = _verify_governance(
        root=root,
        events=events,
        rekor=rekor,
        relation=relation,
        protocol=protocol,
        protocol_path=protocol_path,
        events_dir=root / events_dir,
        current_tip=current_tip,
        issuance_deadline=issuance_deadline,
    )

    manifest_req = protocol.get("signed_manifest_requirements", {})
    required_protocols = manifest_req.get("all_protocols_required")
    required_workflows = manifest_req.get("all_production_workflows_required")
    if required_protocols is not None:
        if manifest.get("all_protocols") != required_protocols:
            raise ValueError("signed manifest protocol bundle incomplete")
        for p in required_protocols:
            if p not in manifest.get("paths_sha256", {}):
                raise ValueError("required protocol absent from signed manifest")
    if required_workflows is not None:
        if manifest.get("deployment_workflows") != required_workflows:
            raise ValueError("signed manifest workflow bundle incomplete")
        for p in required_workflows:
            if p not in manifest.get("paths_sha256", {}):
                raise ValueError("required workflow absent from signed manifest")
    governance["complete_deployment_bundle_bound"] = True

    checkpoint_policy = protocol.get("checkpointing", {})
    if checkpoint_policy.get("anchor_required") is not True:
        raise ValueError("admission protocol does not require checkpoint anchor")
    checkpoint_rel = checkpoint_policy.get("checkpoint_path")
    if not isinstance(checkpoint_rel, str) or not checkpoint_rel:
        raise ValueError("admission checkpoint path missing")
    checkpoint_path = root / checkpoint_rel
    checkpoint_bundle = checkpoint_path.with_suffix(".sigstore.json")
    if not checkpoint_path.exists() or not checkpoint_bundle.exists():
        raise ValueError("required signed checkpoint missing")
    checkpoint_state = verify_checkpoint(
        repo_root=root,
        events_dir=root / events_dir,
        checkpoint_path=checkpoint_path,
        checkpoint_bundle_path=checkpoint_bundle,
        manifest=manifest,
        manifest_sha256=digest(canonical(manifest)),
        workflow_path=forecast_workflow,
        current_branch_tip=current_tip,
        verify_blob=verify_forecast_blob,
        verify_workflow_binding=verify_event_workflow_against_manifest,
        expected_head=head,
    )
    interval_events=int(checkpoint_policy.get("interval_events",0))
    if interval_events<=0:
        raise ValueError("checkpoint interval invalid")
    uncheckpointed=len(events)-int(checkpoint_state.sequence)
    if uncheckpointed<0 or uncheckpointed>=interval_events:
        raise ValueError("checkpoint stale beyond frozen interval")
    anchor_branch = checkpoint_policy.get("anchor_branch")
    if not isinstance(anchor_branch, str) or not anchor_branch:
        raise ValueError("admission checkpoint anchor branch missing")
    anchor = verify_latest_anchor(
        repo_root=root,
        anchor_branch=anchor_branch,
        head=head,
        manifest=manifest,
        workflow_path=forecast_workflow,
        current_evidence_tip=current_tip,
        verify_blob=verify_forecast_blob,
        verify_workflow_binding=verify_event_workflow_against_manifest,
    )
    if int(anchor["verified_through_sequence"]) != int(checkpoint_state.sequence):
        raise ValueError("anchor/checkpoint sequence mismatch")
    governance["checkpoint"] = {
        "verified": True,
        "verified_through_sequence": checkpoint_state.sequence,
        "verified_through_event_hash": checkpoint_state.last_event_hash,
        "uncheckpointed_suffix_events": uncheckpointed,
        "maximum_allowed_uncheckpointed_suffix_events": interval_events-1,
    }
    governance["checkpoint_anchor"] = anchor
    governance["independent_checkpoint_anchor_verified"] = True

    score = score_from_events(
        events,
        protocol,
        start_utc=start_utc,
        horizon=horizon,
        allow_admission=False,
    )
    gates = score.get("gates", {})
    passed = bool(gates) and all(bool(v) for v in gates.values())
    score["admission_ready"] = passed
    score["prospective_winner"] = (
        protocol.get("selected_model") if passed else None
    )
    score["status"] = (
        "PROSPECTIVE_GATE_PASS_FULLY_VERIFIED"
        if passed else "PROSPECTIVE_GATE_PENDING_OR_FAIL"
    )
    return {
        "schema": "btc-predictive-vnext4r71-admission-v1",
        "head": head,
        "governance": governance,
        "score": score,
        "admission_ready": passed,
        "trading_authority": False,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    cfg = json.loads(Path(args.config).read_text())
    print(json.dumps(run_admission(**cfg), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
