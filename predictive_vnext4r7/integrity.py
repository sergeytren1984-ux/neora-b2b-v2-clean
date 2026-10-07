"""Integrity primitives for BTC Predictive vNext4R7 remediation.

R7 is a successor candidate. It does not mutate the live R6 epoch.
This module closes the audit gaps around workflow immutability, event uniqueness,
and canonical slot/time relationships.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

UTC = timezone.utc
SLOT_RE = re.compile(r"^\d{8}T\d{6}Z$")
HEX40_RE = re.compile(r"^[0-9a-f]{40}$")


def canonical(obj) -> bytes:
    return (
        json.dumps(
            obj,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode()


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_utc(value) -> datetime:
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def slot_to_time(slot: str) -> datetime:
    if not isinstance(slot, str) or SLOT_RE.fullmatch(slot) is None:
        raise ValueError("invalid canonical slot")
    return datetime.strptime(slot, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)


def git_bytes(repo_root: Path, commit: str, path: str) -> bytes:
    if HEX40_RE.fullmatch(str(commit)) is None:
        raise ValueError("invalid git commit sha")
    return subprocess.run(
        ["git", "-C", str(repo_root), "show", f"{commit}:{path}"],
        check=True,
        capture_output=True,
        timeout=120,
    ).stdout


def workflow_digest_at_commit(repo_root: Path, commit: str, path: str) -> str:
    return digest(git_bytes(repo_root, commit, path))


def expected_idempotency_key(event: dict) -> str | None:
    et = event.get("type")
    head = event.get("head")
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
    return None


def event_uniqueness_key(event: dict):
    et = event.get("type")
    head = event.get("head")
    slot = event.get("slot")
    if et in {"SCHEDULE_REGISTERED", "CONFIG_FROZEN_PRESTART"}:
        return (et, head, None)
    if et in {
        "FORECAST_ISSUED",
        "DELIVERY_CONFIRMED",
        "OUTCOME_RECORDED",
        "SLOT_MISSED",
    }:
        return (et, head, slot)
    return None


def validate_event_semantics(event: dict, *, head: str, horizon: timedelta) -> None:
    if event.get("head") not in (None, head):
        raise ValueError("event head mismatch")

    expected_key = expected_idempotency_key(event)
    if expected_key is not None and event.get("idempotency_key") != expected_key:
        raise ValueError("non-canonical idempotency key")

    et = event.get("type")
    if et in {
        "FORECAST_ISSUED",
        "DELIVERY_CONFIRMED",
        "OUTCOME_RECORDED",
        "SLOT_MISSED",
        "ABSTAIN_DATA_INVALID",
    }:
        slot = event.get("slot")
        slot_time = slot_to_time(slot)
        anchor_text = event.get("anchor_utc")

        if et in {"FORECAST_ISSUED", "OUTCOME_RECORDED"}:
            if anchor_text is None:
                raise ValueError("anchor_utc required")
            anchor = parse_utc(anchor_text)
            if anchor != slot_time:
                raise ValueError("slot/anchor mismatch")

        if et == "FORECAST_ISSUED":
            due = parse_utc(event.get("due_utc"))
            if due != slot_time + horizon:
                raise ValueError("forecast due/horizon mismatch")

        if et == "OUTCOME_RECORDED":
            due = parse_utc(event.get("due_utc"))
            if due != slot_time + horizon:
                raise ValueError("outcome due/horizon mismatch")

        if et == "DELIVERY_CONFIRMED":
            target_sequence = event.get("target_sequence")
            target_hash = event.get("target_event_hash")
            if not isinstance(target_sequence, int) or target_sequence <= 0:
                raise ValueError("delivery target_sequence invalid")
            if not isinstance(target_hash, str) or len(target_hash) != 64:
                raise ValueError("delivery target_event_hash invalid")


def validate_event_collection(events: list[dict], *, head: str, horizon: timedelta) -> None:
    idempotency = set()
    uniqueness = set()
    previous = None
    for i, event in enumerate(events, 1):
        if int(event.get("sequence", -1)) != i:
            raise ValueError("event sequence gap")
        if event.get("previous_hash") != previous:
            raise ValueError("event previous_hash mismatch")
        if canonical(event) != canonical(json.loads(canonical(event))):
            raise ValueError("canonical serialization failure")

        key = event.get("idempotency_key")
        if not isinstance(key, str) or key in idempotency:
            raise ValueError("duplicate or missing idempotency key")
        idempotency.add(key)

        unique = event_uniqueness_key(event)
        if unique is not None:
            if unique in uniqueness:
                raise ValueError("duplicate (type,head,slot)")
            uniqueness.add(unique)

        validate_event_semantics(event, head=head, horizon=horizon)
        previous = digest(canonical(event))


def verify_event_workflow_against_manifest(
    repo_root: Path,
    event: dict,
    workflow_path: str,
    manifest: dict,
) -> str:
    """Independently bind an event's workflow commit to the frozen manifest."""
    commit = str(event.get("workflow_commit", "")).lower()
    if HEX40_RE.fullmatch(commit) is None:
        raise ValueError("invalid event workflow_commit")
    frozen = manifest.get("paths_sha256", {}).get(workflow_path)
    if not isinstance(frozen, str) or len(frozen) != 64:
        raise ValueError("workflow path absent from signed manifest")
    actual = workflow_digest_at_commit(repo_root, commit, workflow_path)
    if actual != frozen:
        raise ValueError(
            "event workflow content differs from signed frozen manifest"
        )
    return actual


def verify_static_source_against_manifest(
    repo_root: Path,
    manifest: dict,
    source_paths: list[str],
) -> None:
    source = manifest.get("source_commit_sha")
    if not isinstance(source, str) or HEX40_RE.fullmatch(source) is None:
        raise ValueError("invalid frozen source commit")
    hashes = manifest.get("paths_sha256", {})
    for path in source_paths:
        want = hashes.get(path)
        if not isinstance(want, str):
            raise ValueError("static path absent from manifest: " + path)
        got = digest(git_bytes(repo_root, source, path))
        if got != want:
            raise ValueError("immutable source path hash mismatch: " + path)
