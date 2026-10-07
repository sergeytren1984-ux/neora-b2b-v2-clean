"""Deterministic full numerical worker lifecycle using the frozen R6 artifacts.

This is an engineering E2E fixture, not a prospective market result. It invokes
the production R7.1 worker forecast/outcome functions while replacing only
external time/data/publication I/O. Feature extraction, artifact loading,
ensemble prediction, adaptive control, barrier construction and outcome
classification are the production implementations and use the exact frozen R6
artifact/baseline bytes declared by each protocol.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from predictive_vnext4r71 import worker

UTC=timezone.utc
ROOT=Path(__file__).resolve().parents[1]
FIXED_NOW=datetime(2026,10,7,12,1,0,tzinfo=UTC)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def deterministic_closed_rows(anchor,cfg):
    n=max(int(cfg["min_history"])+32,420 if cfg["interval"]=="15m" else 220)
    step=int(cfg["duration_ms"])
    start_ms=int(anchor.timestamp()*1000)-n*step
    rows=[]
    previous=82000.0
    for i in range(n):
        t=float(i)
        close=82000.0*math.exp(
            0.000025*t
            +0.0025*math.sin(t/11.0)
            +0.0012*math.cos(t/29.0)
        )
        open_price=previous
        spread=0.0016+0.00025*(1.0+math.sin(t/13.0))
        high=max(open_price,close)*(1.0+spread)
        low=min(open_price,close)*(1.0-spread*0.92)
        volume=900.0+80.0*math.sin(t/17.0)+0.35*t
        trades=4200+int(160*math.cos(t/23.0))+i
        taker=volume*(0.48+0.07*math.sin(t/9.0))
        open_ms=start_ms+i*step
        close_ms=open_ms+step-1
        rows.append([
            open_ms,
            f"{open_price:.12f}",
            f"{high:.12f}",
            f"{low:.12f}",
            f"{close:.12f}",
            f"{volume:.12f}",
            close_ms,
            "0",
            trades,
            f"{taker:.12f}",
        ])
        previous=close
    return rows


def deterministic_outcome_rows(forecast,cfg):
    anchor=datetime.fromisoformat(forecast["anchor_utc"])
    ref=float(forecast["reference_price"])
    lower=float(forecast["lower_price"])
    upper=float(forecast["upper_price"])
    step=int(cfg["duration_ms"])
    rows=[]
    for i in range(int(cfg["bars"])):
        open_ms=int(anchor.timestamp()*1000)+i*step
        close_ms=open_ms+step-1
        high=(ref+upper)/2.0
        low=(ref+lower)/2.0
        if i==1:
            low=lower-abs(ref-lower)*0.05-1e-9
        rows.append([
            open_ms,ref,high,low,ref,1.0,close_ms,0,1,0.5
        ])
    return rows


def run_head(head):
    cfg=copy.deepcopy(worker.CONFIG[head])
    protocol_path=ROOT/cfg["protocol"]
    protocol=json.loads(protocol_path.read_bytes())
    artifact_path=ROOT/cfg["artifact"]
    baseline_path=ROOT/cfg["baseline"]
    actual_artifact_sha=sha256(artifact_path)
    actual_baseline_sha=sha256(baseline_path)
    if actual_artifact_sha!=protocol["artifact_sha256"]:
        raise RuntimeError(head+": real R6 artifact hash differs from protocol")
    if actual_baseline_sha!=protocol["baseline_sha256"]:
        raise RuntimeError(head+": real R6 baseline hash differs from protocol")

    anchor=worker.slot_floor(FIXED_NOW,cfg["cadence"])
    rows=deterministic_closed_rows(anchor,cfg)
    published=[]
    old_root=worker.EVIDENCE_ROOT
    old_start=worker.START
    try:
        with tempfile.TemporaryDirectory(prefix="r75-numerical-"+head+"-") as td:
            worker.EVIDENCE_ROOT=Path(td)
            worker.START=anchor-timedelta(days=2)

            def capture_publish(_cfg,obj,deadline=None,attachments=()):
                published.append(copy.deepcopy(obj))

            with (
                patch.object(worker,"utcnow",return_value=FIXED_NOW),
                patch.object(worker,"verify_signed_freeze",return_value=[]),
                patch.object(worker,"fetch_recent",return_value=(rows,rows)),
                patch.object(worker,"publish",side_effect=capture_publish),
            ):
                if worker.forecast(cfg,head) is not True:
                    raise RuntimeError(head+": production forecast path did not emit")

            forecasts=[x for x in published if x.get("type")=="FORECAST_ISSUED"]
            if len(forecasts)!=1:
                raise RuntimeError(head+": expected exactly one forecast")
            forecast=forecasts[0]
            if forecast["artifact_sha256"]!=actual_artifact_sha:
                raise RuntimeError(head+": emitted artifact hash mismatch")
            if forecast["baseline_sha256"]!=actual_baseline_sha:
                raise RuntimeError(head+": emitted baseline hash mismatch")
            if forecast["selected_model"]!="ensemble_equal":
                raise RuntimeError(head+": frozen selected model changed")
            probs=forecast["class_distribution"]
            if abs(sum(float(v) for v in probs.values())-1.0)>1e-8:
                raise RuntimeError(head+": invalid forecast distribution")
            if not (
                float(forecast["lower_price"])<float(forecast["reference_price"])
                <float(forecast["upper_price"])
            ):
                raise RuntimeError(head+": invalid numerical barriers")

            published.clear()
            due=datetime.fromisoformat(forecast["due_utc"])
            outcome_rows=deterministic_outcome_rows(forecast,cfg)
            with (
                patch.object(worker,"utcnow",return_value=due+timedelta(minutes=1)),
                patch.object(
                    worker,"verify_signed_freeze",
                    return_value=[(forecast,None)],
                ),
                patch.object(
                    worker,"fetch_outcome_rows",
                    return_value=outcome_rows,
                ),
                patch.object(worker,"publish",side_effect=capture_publish),
            ):
                worker.outcomes(cfg,head)

            outcomes=[x for x in published if x.get("type")=="OUTCOME_RECORDED"]
            if len(outcomes)!=1:
                raise RuntimeError(head+": expected exactly one outcome")
            outcome=outcomes[0]
            if outcome["outcome_class"]!="LOWER_FIRST":
                raise RuntimeError(head+": deterministic outcome classification drift")
            return {
                "head":head,
                "fixture":"DETERMINISTIC_ENGINEERING_NOT_MARKET_EVIDENCE",
                "worker_forecast_function":"predictive_vnext4r71.worker.forecast",
                "worker_outcome_function":"predictive_vnext4r71.worker.outcomes",
                "artifact_path":cfg["artifact"],
                "artifact_sha256":actual_artifact_sha,
                "baseline_path":cfg["baseline"],
                "baseline_sha256":actual_baseline_sha,
                "selected_model":forecast["selected_model"],
                "class_distribution":forecast["class_distribution"],
                "control":forecast["control"],
                "reference_price":forecast["reference_price"],
                "lower_price":forecast["lower_price"],
                "upper_price":forecast["upper_price"],
                "outcome_class":outcome["outcome_class"],
                "trading_authority":False,
            }
    finally:
        worker.EVIDENCE_ROOT=old_root
        worker.START=old_start


def run():
    heads=[run_head(h) for h in ("1h","4h","24h")]
    expected={
        "1h":(
            "9ccbcc3799a3be27e383b862213629ce268aace919a1c5aecf097a05ae1a04f5",
            "83bae4ddb9b72a545edd74e3a44da297c2748c15c4bfee77299631adfa5b86c4",
        ),
        "4h":(
            "c386489ec54eb441fab7666036c5dcb1fca72e3ad7aa89fc32bf8e3575c04726",
            "d4449b18d96162755d938d7b8b6da5ee126466ad9e4253ccac24d2c4d8c655",
        ),
        "24h":(
            "852ec232cd798d3939d50301dd0b3d30fb7e11e51ea3b6b1b5b9761abef57e09",
            "0685e147c38a62701ce4e9c11acb349461cdabe70f2b8f67c81c07abab056357",
        ),
    }
    for row in heads:
        if (
            row["artifact_sha256"],row["baseline_sha256"]
        )!=expected[row["head"]]:
            raise RuntimeError(row["head"]+": audited R6 hash contract changed")
    return {
        "schema":"btc-predictive-vnext4r75-real-r6-numerical-lifecycle-v1",
        "status":"PASS",
        "purpose":"ENGINEERING_NUMERICAL_LIFECYCLE_NOT_PROSPECTIVE_SKILL",
        "real_r6_artifact_and_baseline_bytes":True,
        "e2e_dummy_model_used":False,
        "external_market_io_replaced_by_deterministic_fixture":True,
        "production_feature_prediction_control_barrier_outcome_code":True,
        "heads":heads,
        "trading_authority":False,
    }


if __name__=="__main__":
    print(json.dumps(run(),sort_keys=True,indent=2))
