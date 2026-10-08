"""Full-grid adversarial regression for independent re-audit findings R1-F4a..d."""
from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

from predictive_vnext5 import prospective_score as s

START=datetime(2026,10,12,tzinfo=timezone.utc)
DAYS={"1h":42,"4h":42,"24h":60}
HOURS={"1h":1,"4h":4,"24h":24}


def iso(x):
    return x.isoformat()


def row(head,candidate,anchor):
    due=anchor+timedelta(hours=HOURS[head])
    return {
        "schema":"btc-predictive-vnext5r2-canonical-row-v1",
        "query_type":"CANONICAL",
        "target_id":"CANONICAL_SIGMA_1_1_V1",
        "lower_sigma":1.0,
        "upper_sigma":1.0,
        "head":head,
        "candidate_id":candidate,
        "anchor_utc":iso(anchor),
        "forecast_issued_at_utc":iso(anchor+timedelta(minutes=1)),
        "due_utc":iso(due),
        "outcome_recorded_at_utc":iso(due),
        "prediction_raw":[1.0,0.0,0.0,0.0],
        "outcome_class":0,
        "volatility":0.002,
    }


def rows(head):
    n=DAYS[head]*24//HOURS[head]
    out=[]
    for i in range(n):
        a=START+timedelta(hours=i*HOURS[head])
        for candidate in s.expected_candidates(head):
            out.append(row(head,candidate,a))
    return out


def must_reject(label,fn,contains=None):
    try:
        fn()
    except Exception as exc:
        message=str(exc)
        if contains and contains not in message:
            raise AssertionError(f"{label}: wrong rejection: {message}") from exc
        return message
    raise AssertionError(f"{label}: attack was accepted")


def main():
    runtime=s.authoritative_runtime()
    report={}
    for head in ("1h","4h","24h"):
        base=rows(head)
        cutoff=START+timedelta(days=DAYS[head])
        valid=s.score(base,head,iso(START),iso(cutoff))
        attacks={}

        x=copy.deepcopy(base)
        for r in x:
            r["forecast_issued_at_utc"]=iso(START-timedelta(days=1))
        attacks["pre_anchor_forecast"]=must_reject(
            "pre_anchor_forecast",
            lambda: s.score(x,head,iso(START),iso(cutoff)),
            "before anchor",
        )

        x=copy.deepcopy(base)
        for r in x:
            r["outcome_class"]=0.5
        attacks["fractional_outcome"]=must_reject(
            "fractional_outcome",
            lambda: s.score(x,head,iso(START),iso(cutoff)),
            "strict integer",
        )

        x=copy.deepcopy(base)
        for r in x:
            r["query_type"]="CUSTOM_ZONE"
            r["lower_sigma"]=0.5
            r["upper_sigma"]=2.0
        attacks["custom_pair"]=must_reject(
            "custom_pair",
            lambda: s.score(x,head,iso(START),iso(cutoff)),
            "custom/non-canonical",
        )

        x=copy.deepcopy(base)
        for r in x:
            r["outcome_recorded_at_utc"]=iso(cutoff+timedelta(days=1))
        attacks["post_cutoff_outcome"]=must_reject(
            "post_cutoff_outcome",
            lambda: s.score(x,head,iso(START),iso(cutoff)),
            "after evaluation cutoff",
        )

        changed=copy.deepcopy(runtime)
        changed["heads"][head]["volatility_bin_edges"]=[10.0,20.0]
        attacks["modified_runtime"]=must_reject(
            "modified_runtime",
            lambda: s.score(base,head,iso(START),iso(cutoff),changed),
            "non-authoritative runtime",
        )

        x=copy.deepcopy(base)
        x.append(copy.deepcopy(x[0]))
        attacks["duplicate"]=must_reject(
            "duplicate",
            lambda: s.score(x,head,iso(START),iso(cutoff)),
            "duplicate prospective row",
        )

        x=copy.deepcopy(base)
        x.pop(0)
        attacks["missing_due"]=must_reject(
            "missing_due",
            lambda: s.score(x,head,iso(START),iso(cutoff)),
            "incomplete due grid",
        )

        if head=="24h":
            x=copy.deepcopy(base)
            x[1]["outcome_class"]=1
            attacks["challenger_outcome_mismatch"]=must_reject(
                "challenger_outcome_mismatch",
                lambda: s.score(x,head,iso(START),iso(cutoff)),
                "challenger outcome/volatility mismatch",
            )

        report[head]={
            "valid_expected_due_windows":valid["expected_due_windows"],
            "valid_admission_ready":valid["admission_ready"],
            "attacks_rejected":sorted(attacks),
            "messages":attacks,
        }

    # The old CLI attack must no longer be expressible: --runtime is not accepted.
    with tempfile.TemporaryDirectory() as td:
        p=Path(td)/"rows.jsonl"
        p.write_text("\n".join(json.dumps(x,separators=(",",":")) for x in rows("4h"))+"\n")
        proc=subprocess.run(
            [
                sys.executable,
                str(Path(s.__file__).resolve()),
                "--events-jsonl",str(p),
                "--head","4h",
                "--start-utc",iso(START),
                "--cutoff-utc",iso(START+timedelta(days=42)),
                "--runtime","/tmp/attacker-runtime.json",
            ],
            capture_output=True,text=True,
        )
        if proc.returncode==0 or "unrecognized arguments: --runtime" not in proc.stderr:
            raise AssertionError("CLI runtime override unexpectedly accepted")
        report["cli_runtime_override"]="REJECTED"

    print(json.dumps({
        "status":"VNEXT5R2_F4_ADVERSARIAL_REGRESSION_PASS",
        "report":report,
        "prospective_skill_proven":False,
        "trading_authority":False,
    },indent=2,sort_keys=True))


if __name__=="__main__":
    main()
