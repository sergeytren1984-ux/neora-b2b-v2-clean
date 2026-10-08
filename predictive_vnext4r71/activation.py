"""Exclusive admission consumer for future trading activation.

R7.6 does not grant trading authority.  This module defines the only allowed
shape for a future side-effecting consumer: it must execute inside the exact
signed activation workflow while that job holds the same GitHub Actions
concurrency group as the evidence writer for the selected head.

The provider concurrency group is the cross-process lease.  The snapshot
freshness guard is checked immediately before and after the callback.  The
post-check is audit evidence, not a substitute for the exclusive lease.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Callable, Any

from predictive_vnext4r71.admission import assert_snapshot_decision_current

LEASE_PROVIDER = "github-actions-concurrency"
ACTIVATION_WORKFLOW = ".github/workflows/btc-predictive-vnext4r76-activation.yml"


def expected_concurrency_group(head: str) -> str:
    if head not in {"1h", "4h", "24h"}:
        raise ValueError("invalid activation head")
    return f"btc-predictive-vnext4r71-{head}-unified-chain"


def validate_exclusive_consumer_context(*, head: str) -> dict:
    """Fail closed unless the exact signed activation workflow owns the lease."""
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise RuntimeError("activation requires GitHub Actions provider lease")
    if os.environ.get("GITHUB_EVENT_NAME") != "workflow_dispatch":
        raise RuntimeError("activation requires workflow_dispatch")
    if os.environ.get("BTC_VNEXT4R76_LEASE_PROVIDER") != LEASE_PROVIDER:
        raise RuntimeError("activation lease provider missing")
    expected_group = expected_concurrency_group(head)
    if os.environ.get("BTC_VNEXT4R76_LEASE_GROUP") != expected_group:
        raise RuntimeError("activation concurrency lease group mismatch")

    source = os.environ.get("BTC_VNEXT4R71_SOURCE_SHA", "")
    workflow_sha = os.environ.get("GITHUB_SHA", "")
    if len(source) != 40 or source != workflow_sha:
        raise RuntimeError("activation workflow SHA is not exact immutable source")

    workflow_path = os.environ.get("BTC_VNEXT4R76_ACTIVATION_WORKFLOW")
    if workflow_path != ACTIVATION_WORKFLOW:
        raise RuntimeError("unexpected activation workflow path")

    return {
        "lease_provider": LEASE_PROVIDER,
        "lease_group": expected_group,
        "source_sha": source,
        "workflow_path": workflow_path,
    }


def validate_report_for_side_effect(*, report: dict, head: str) -> None:
    if report.get("head") != head:
        raise ValueError("activation report head mismatch")
    if report.get("admission_ready") is not True:
        raise RuntimeError("activation requires admission_ready=true")
    if report.get("trading_authority") is not True:
        raise RuntimeError("trading authority not granted")
    binding = report.get("governance", {}).get("decision_binding", {})
    if binding.get("semantics") != "SNAPSHOT_AS_OF_EXACT_EVIDENCE_SHA":
        raise ValueError("activation requires exact snapshot decision binding")


def consume_under_exclusive_lease(
    *,
    repo_root: str,
    report: dict,
    head: str,
    side_effect: Callable[[], Any],
) -> dict:
    """Execute one side effect only while the provider lease is held.

    All production evidence writers for *head* are bound to the same concurrency
    group in the signed deployment manifest.  Therefore the activation workflow
    and evidence writer cannot execute simultaneously.  A fresh remote-tip check
    is still mandatory immediately before the callback.
    """
    context = validate_exclusive_consumer_context(head=head)
    validate_report_for_side_effect(report=report, head=head)
    evidence_sha = assert_snapshot_decision_current(
        repo_root=repo_root,
        report=report,
    )
    result = side_effect()
    after = assert_snapshot_decision_current(
        repo_root=repo_root,
        report=report,
    )
    if after != evidence_sha:
        raise RuntimeError("evidence SHA changed despite exclusive lease")
    return {
        "status": "SIDE_EFFECT_EXECUTED_UNDER_EXCLUSIVE_LEASE",
        "head": head,
        "evidence_sha": evidence_sha,
        "lease": context,
        "result": result,
    }


def validate_only(*, repo_root: str, report: dict, head: str) -> dict:
    """Validate lease context and snapshot freshness without any side effect."""
    context = validate_exclusive_consumer_context(head=head)
    evidence_sha = assert_snapshot_decision_current(
        repo_root=repo_root,
        report=report,
    )
    return {
        "status": "ACTIVATION_PATH_VALIDATED_NO_SIDE_EFFECT",
        "head": head,
        "evidence_sha": evidence_sha,
        "lease": context,
        "trading_authority": bool(report.get("trading_authority", False)),
    }


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--repo-root", required=True)
    p.add_argument("--report", required=True)
    p.add_argument("--head", required=True, choices=("1h", "4h", "24h"))
    p.add_argument("--validate-only", action="store_true")
    args = p.parse_args(argv)
    report = json.loads(Path(args.report).read_text())
    if not args.validate_only:
        raise SystemExit(
            "R7.6 CLI is validation-only; any future side effect must call "
            "consume_under_exclusive_lease from the exact signed workflow"
        )
    print(json.dumps(
        validate_only(
            repo_root=args.repo_root,
            report=report,
            head=args.head,
        ),
        sort_keys=True,
        separators=(",", ":"),
    ))


if __name__ == "__main__":
    main()
