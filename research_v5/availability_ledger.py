"""Point-in-time admission contract for NFP, PCE and ISM research factors.

This module does not collect or infer missing releases. A release becomes
usable only after an archived, hashed observation was actually seen.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from urllib.parse import urlparse

ALLOWED = {
    "NFP": ("bls.gov",),
    "PCE": ("bea.gov",),
    "ISM_MANUFACTURING": ("ismworld.org",),
    "ISM_SERVICES": ("ismworld.org",),
}


def utc(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("timezone required")
    return result.astimezone(timezone.utc)


def validate(record: dict, raw: bytes) -> dict:
    """Return a validated availability record; no caller-supplied future backfill."""
    required = {"event", "observation_period", "source_url", "scheduled_utc",
                "published_utc", "first_seen_utc", "capture_utc", "raw_sha256",
                "revision_id", "value_status"}
    if set(record) != required:
        raise ValueError("missing or unregistered ledger fields")
    event = record["event"]
    if event not in ALLOWED:
        raise ValueError("unknown release type")
    url = urlparse(record["source_url"])
    if url.scheme != "https" or not any(
            url.hostname == domain or (url.hostname or "").endswith("." + domain)
            for domain in ALLOWED[event]):
        raise ValueError("source domain not authorized")
    if hashlib.sha256(raw).hexdigest() != record["raw_sha256"]:
        raise ValueError("raw digest mismatch")
    scheduled, published, first_seen, capture = (utc(record[k]) for k in
        ("scheduled_utc", "published_utc", "first_seen_utc", "capture_utc"))
    if not scheduled <= published <= first_seen <= capture:
        raise ValueError("availability chronology invalid")
    if not record["observation_period"] or not record["revision_id"]:
        raise ValueError("period or revision absent")
    if record["value_status"] not in ("RAW_CAPTURED", "PARSED_VALIDATED"):
        raise ValueError("invented or unvalidated data status")
    return {**record, "available_from_utc": capture.isoformat(),
            "numeric_admission": False}


def asof(record: dict, raw: bytes, anchor_utc: str) -> dict | None:
    v = validate(record, raw)
    return v if utc(v["available_from_utc"]) <= utc(anchor_utc) else None
