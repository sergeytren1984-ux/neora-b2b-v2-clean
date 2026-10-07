"""Strict event and relationship validation for BTC Predictive vNext4R7.1.

This module is the mandatory semantic gate used before any admission statistics.
It deliberately rejects unknown event types, head drift, early outcomes, malformed
receipts, duplicate slot/type records, and forecast/miss coexistence.
"""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path
import json

from predictive_vnext4r7.integrity import (
    canonical,
    digest,
    parse_utc,
    slot_to_time,
    verify_event_workflow_against_manifest,
)

REQUIRED_PROTOCOLS = (
    "predictive_vnext4r71/protocol_1h.json",
    "predictive_vnext4r71/protocol_4h.json",
    "predictive_vnext4r71/protocol_24h.json",
)
REQUIRED_PRODUCTION_WORKFLOWS = (
    ".github/workflows/btc-predictive-vnext4r71-1h.yml",
    ".github/workflows/btc-predictive-vnext4r71-4h.yml",
    ".github/workflows/btc-predictive-vnext4r71-24h.yml",
    ".github/workflows/btc-predictive-vnext4r71-watchdog.yml",
    ".github/workflows/btc-predictive-vnext4r71-health.yml",
)

ALLOWED_TYPES = {
    "SCHEDULE_REGISTERED",
    "CONFIG_FROZEN_PRESTART",
    "FORECAST_ISSUED",
    "DELIVERY_CONFIRMED",
    "OUTCOME_RECORDED",
    "SLOT_MISSED",
    "ABSTAIN_DATA_INVALID",
}


def _canonical_key(event: dict) -> str:
    et = event["type"]
    head = event["head"]
    slot = event.get("slot")
    if et == "SCHEDULE_REGISTERED":
        return f"{head}:schedule"
    if et == "CONFIG_FROZEN_PRESTART":
        return f"{head}:freeze"
    if et == "FORECAST_ISSUED":
        return f"forecast:{slot}"
    if et == "DELIVERY_CONFIRMED":
        return f"delivery:forecast:{slot}"
    if et == "OUTCOME_RECORDED":
        return f"outcome:{slot}"
    if et == "SLOT_MISSED":
        return f"missed:{slot}"
    if et == "ABSTAIN_DATA_INVALID":
        return f"abstain-data:{slot}"
    raise ValueError("unsupported event type")


def _require_slot(event: dict):
    slot = event.get("slot")
    if not isinstance(slot, str):
        raise ValueError("slot required")
    return slot, slot_to_time(slot)


def validate_event_collection(
    events: list[dict],
    *,
    head: str,
    horizon: timedelta,
    issuance_deadline: timedelta,
) -> dict:
    previous = None
    idempotency = set()
    type_slot = set()
    forecasts = {}
    receipts = {}
    outcomes = {}
    missed = {}
    schedule = []
    freeze = []

    for i, event in enumerate(events, 1):
        if event.get("type") not in ALLOWED_TYPES:
            raise ValueError("unknown event type")
        if event.get("head") != head:
            raise ValueError("event head mismatch")
        if int(event.get("sequence", -1)) != i:
            raise ValueError("event sequence gap")
        if event.get("previous_hash") != previous:
            raise ValueError("event previous_hash mismatch")
        if event.get("idempotency_key") != _canonical_key(event):
            raise ValueError("non-canonical idempotency key")
        if event["idempotency_key"] in idempotency:
            raise ValueError("duplicate idempotency key")
        idempotency.add(event["idempotency_key"])

        et = event["type"]
        if et in {"SCHEDULE_REGISTERED", "CONFIG_FROZEN_PRESTART"}:
            unique = (et, head, None)
        else:
            slot, slot_time = _require_slot(event)
            unique = (et, head, slot)
        if unique in type_slot:
            raise ValueError("duplicate (type,head,slot)")
        type_slot.add(unique)

        if et == "SCHEDULE_REGISTERED":
            schedule.append(event)
        elif et == "CONFIG_FROZEN_PRESTART":
            freeze.append(event)
        elif et == "FORECAST_ISSUED":
            slot, slot_time = _require_slot(event)
            if parse_utc(event.get("anchor_utc")) != slot_time:
                raise ValueError("forecast slot/anchor mismatch")
            due = parse_utc(event.get("due_utc"))
            if due != slot_time + horizon:
                raise ValueError("forecast due/horizon mismatch")
            published = parse_utc(event.get("published_at_utc"))
            if published < slot_time:
                raise ValueError("forecast published before anchor")
            if published >= slot_time + issuance_deadline:
                raise ValueError("forecast published after deadline")
            forecasts[slot] = event
        elif et == "DELIVERY_CONFIRMED":
            slot, slot_time = _require_slot(event)
            receipts[slot] = event
        elif et == "OUTCOME_RECORDED":
            slot, slot_time = _require_slot(event)
            if parse_utc(event.get("anchor_utc")) != slot_time:
                raise ValueError("outcome slot/anchor mismatch")
            due = parse_utc(event.get("due_utc"))
            if due != slot_time + horizon:
                raise ValueError("outcome due/horizon mismatch")
            if parse_utc(event.get("published_at_utc")) < due:
                raise ValueError("outcome published before due")
            outcomes[slot] = event
        elif et == "SLOT_MISSED":
            slot, slot_time = _require_slot(event)
            deadline = parse_utc(event.get("deadline_utc"))
            if deadline != slot_time + issuance_deadline:
                raise ValueError("missed deadline mismatch")
            if parse_utc(event.get("published_at_utc")) < deadline:
                raise ValueError("slot marked missed before deadline")
            missed[slot] = event
        elif et == "ABSTAIN_DATA_INVALID":
            _require_slot(event)

        previous = digest(canonical(event))

    if len(schedule) != 1:
        raise ValueError("schedule count must equal one")
    if len(freeze) != 1:
        raise ValueError("freeze count must equal one")

    for slot, forecast in forecasts.items():
        if slot in missed:
            raise ValueError("forecast and missed coexist for slot")
        receipt = receipts.get(slot)
        if receipt is None:
            continue
        if receipt.get("target_sequence") != forecast.get("sequence"):
            raise ValueError("receipt target_sequence mismatch")
        if receipt.get("target_event_hash") != digest(canonical(forecast)):
            raise ValueError("receipt target_event_hash mismatch")
        deadline = slot_to_time(slot) + issuance_deadline
        if parse_utc(receipt.get("deadline_utc")) != deadline:
            raise ValueError("receipt deadline mismatch")
        if parse_utc(receipt.get("published_at_utc")) >= deadline:
            raise ValueError("receipt published after deadline")

    for slot, receipt in receipts.items():
        if slot not in forecasts:
            raise ValueError("receipt without forecast")

    for slot, outcome in outcomes.items():
        forecast = forecasts.get(slot)
        if forecast is None:
            raise ValueError("outcome without forecast")
        if outcome.get("due_utc") != forecast.get("due_utc"):
            raise ValueError("outcome/forecast due mismatch")
        for key in ("lower_price", "upper_price"):
            if float(outcome.get(key)) != float(forecast.get(key)):
                raise ValueError("outcome barrier mismatch")

    return {
        "forecast_count": len(forecasts),
        "receipt_count": len(receipts),
        "outcome_count": len(outcomes),
        "missed_count": len(missed),
        "schedule": schedule[0],
        "freeze": freeze[0],
    }


def safe_repo_relative_path(repo_root: Path, value: str) -> tuple[Path, str]:
    if not isinstance(value, str) or not value:
        raise ValueError("repository path missing")
    rel = Path(value)
    if rel.is_absolute() or ".." in rel.parts:
        raise ValueError("unsafe repository-relative path")
    root = repo_root.resolve()
    resolved = (root / rel).resolve()
    try:
        normalized = str(resolved.relative_to(root))
    except ValueError as ex:
        raise ValueError("repository path escapes checkout") from ex
    if normalized != value:
        raise ValueError("repository path is not canonical relative path")
    return resolved, normalized


def verify_raw_attachments(
    repo_root: Path,
    events: list[dict],
    *,
    head: str,
) -> None:
    required_prefix = f"predictive_vnext4r71_{head}_raw/"
    for event in events:
        if event.get("type") not in {"FORECAST_ISSUED", "OUTCOME_RECORDED"}:
            continue
        raw_path = event.get("raw_path")
        raw_sha = event.get("raw_sha256")
        if not isinstance(raw_sha, str) or len(raw_sha) != 64:
            raise ValueError("raw attachment metadata missing")
        path, normalized = safe_repo_relative_path(repo_root, raw_path)
        if not normalized.startswith(required_prefix):
            raise ValueError("raw attachment outside frozen head raw prefix")
        if not path.exists() or digest(path.read_bytes()) != raw_sha:
            raise ValueError("raw attachment hash mismatch")


def verify_deployment_bundle_against_manifest(
    repo_root: Path,
    event: dict,
    manifest: dict,
) -> None:
    """Bind every production workflow at the event's signing commit.

    A later commit cannot keep the active head workflow unchanged while silently
    altering watchdog/health/another head and still remain admission-valid.
    """
    deployment = manifest.get("deployment_workflows")
    protocols = manifest.get("all_protocols")
    if deployment != list(REQUIRED_PRODUCTION_WORKFLOWS):
        raise ValueError("signed manifest production workflow set is not exact")
    if protocols != list(REQUIRED_PROTOCOLS):
        raise ValueError("signed manifest protocol set is not exact")
    hashes = manifest.get("paths_sha256", {})
    for required in (*REQUIRED_PROTOCOLS, *REQUIRED_PRODUCTION_WORKFLOWS):
        if required not in hashes:
            raise ValueError("required deployment path absent from signed manifest")
    for workflow_path in REQUIRED_PRODUCTION_WORKFLOWS:
        verify_event_workflow_against_manifest(
            repo_root, event, workflow_path, manifest
        )


def verify_all_workflow_bindings(
    repo_root: Path,
    events: list[dict],
    manifest: dict,
    *,
    forecast_workflow: str,
    outcome_workflow: str,
) -> None:
    seen_commits = set()
    for event in events:
        workflow = (
            outcome_workflow
            if event.get("type") == "OUTCOME_RECORDED"
            else forecast_workflow
        )
        verify_event_workflow_against_manifest(
            repo_root, event, workflow, manifest
        )
        commit = str(event.get("workflow_commit", "")).lower()
        if commit not in seen_commits:
            verify_deployment_bundle_against_manifest(
                repo_root, event, manifest
            )
            seen_commits.add(commit)
