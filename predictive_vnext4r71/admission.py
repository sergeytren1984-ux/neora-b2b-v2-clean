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
from predictive_vnext4r71.checkpoint import event_files
from predictive_vnext4r71.anchor import verify_latest_anchor
from predictive_vnext4r71.crypto import make_blob_verifier
from predictive_vnext4r71.integrity import (
    validate_event_collection,
    verify_raw_attachments,
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

    for event in events:
        workflow = (
            outcome_workflow
            if event.get("type") == "OUTCOME_RECORDED"
            else forecast_workflow
        )
        verify_event_workflow_against_manifest(root, event, workflow, manifest)

    _verify_manifest_source(
        root, manifest, {forecast_workflow, outcome_workflow}
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
    forecast_workflow: str,
    outcome_workflow: str,
    head: str,
    start_utc: datetime,
    horizon: timedelta,
    issuance_deadline: timedelta,
    repository: str,
    expected_ref: str = "refs/heads/main",
    expected_trigger: str = "workflow_dispatch",
    current_tip: str | None = None,
):
    root = Path(repo_root).resolve()
    protocol = json.loads((root / protocol_path).read_text())

    # The signed protocol is authoritative. A caller cannot override this flag.
    if protocol.get("admission_enabled") is not True:
        return {
            "schema": "btc-predictive-vnext4r71-admission-v1",
            "head": head,
            "admission_ready": False,
            "status": "BLOCKED_PROTOCOL_ADMISSION_DISABLED",
            "trading_authority": False,
        }

    if protocol.get("head") != head:
        raise ValueError("protocol head mismatch")
    if current_tip is None:
        current_tip = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        ).stdout.strip()

    # Verifiers are constructed internally from the signed execution contract.
    # The public admission API has no callback or "skip verification" parameter.
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

    checkpoint_policy = protocol.get("checkpointing", {})
    if checkpoint_policy.get("anchor_required") is not True:
        raise ValueError("admission protocol does not require checkpoint anchor")
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
    governance["checkpoint_anchor"] = anchor
    governance["independent_checkpoint_anchor_verified"] = True

    # The numerical layer is permanently non-authoritative.
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
    cfg["start_utc"] = parse_utc(cfg["start_utc"])
    cfg["horizon"] = timedelta(minutes=int(cfg.pop("horizon_minutes")))
    cfg["issuance_deadline"] = timedelta(
        minutes=int(cfg.pop("issuance_deadline_minutes"))
    )
    print(json.dumps(run_admission(**cfg), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
