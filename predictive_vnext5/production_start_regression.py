"""Regression for prospective production signer binding after START.

This covers the exact guard that blocked the first clean epoch: the verified
source SHA, source ref and workflow trigger must survive cryptographic replay
and be accepted by production_journal only when the live GitHub environment
matches all three values.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from predictive_vnext5.production_journal import _assert_current_signer_matches_registration, _prewarmed_anchor
from predictive_vnext5.verified_evidence import VerifiedEvidence

SHA="4678c5529fa3c23e7d9f91c0a7eab7e03424ada7"
REF="refs/heads/btc-predictive-vnext5r43-production-start-remediation-20261009"
TRIGGER="workflow_dispatch"


def expect_reject(verified, env, fragment):
    with patch.dict(os.environ,env,clear=False):
        try:
            _assert_current_signer_matches_registration(verified)
        except RuntimeError as ex:
            if fragment not in str(ex):
                raise AssertionError(f"wrong rejection: {ex}") from ex
        else:
            raise AssertionError("mismatched signer authority unexpectedly accepted")


def main():
    fields=set(VerifiedEvidence.__dataclass_fields__)
    required={"source_commit_sha","source_ref","workflow_trigger"}
    if not required.issubset(fields):
        raise AssertionError("VerifiedEvidence does not expose complete signer authority")

    verified=SimpleNamespace(
        source_commit_sha=SHA,
        source_ref=REF,
        workflow_trigger=TRIGGER,
    )
    good={"GITHUB_SHA":SHA,"GITHUB_REF":REF,"GITHUB_EVENT_NAME":TRIGGER}
    with patch.dict(os.environ,good,clear=False):
        _assert_current_signer_matches_registration(verified)

    expect_reject(
        verified,{**good,"GITHUB_EVENT_NAME":"schedule"},
        "trigger differs",
    )
    expect_reject(
        verified,{**good,"GITHUB_REF":"refs/heads/wrong"},
        "ref differs",
    )
    expect_reject(
        verified,{**good,"GITHUB_SHA":"0"*40},
        "SHA differs",
    )
    now=datetime(2026,10,12,0,1,tzinfo=timezone.utc)
    target="2026-10-12T00:00:00Z"
    assert _prewarmed_anchor("1h",now,target)==datetime(2026,10,12,0,0,tzinfo=timezone.utc)
    for bad in ("2026-10-12T01:00:00Z","2026-10-11T23:00:00Z","2026-10-12T00:01:00Z","2026-10-12T00:00:00+03:00","2026-10-12T00:00:00"):
        try:
            _prewarmed_anchor("1h",now,bad)
        except (ValueError,RuntimeError):
            pass
        else:
            raise AssertionError("prewarmed anchor drift accepted: "+bad)
    # A slot issued after its deadline may never shift to the next anchor.
    late=now+timedelta(hours=1)
    try:
        _prewarmed_anchor("1h",late,target)
    except RuntimeError:
        pass
    else:
        raise AssertionError("stale reserved target drifted into a later slot")
    print("VNEXT5R44_EXACT_ANCHOR_PREWARM_REGRESSION_PASS")


if __name__=="__main__":
    main()
