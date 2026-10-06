"""Adaptive prospective control for BTC Predictive vNext4R6."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

UTC = timezone.utc
ROOT = Path(__file__).resolve().parents[1]


def _parse_utc(value):
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _distribution(values):
    p = np.asarray(values, dtype=float)
    if len(p) != 4 or not np.all(np.isfinite(p)) or np.any(p < 0):
        raise ValueError("invalid control distribution")
    if abs(float(p.sum()) - 1.0) > 1e-8:
        raise ValueError("control distribution does not sum to one")
    return {
        "lower_first": float(p[0]),
        "upper_first": float(p[1]),
        "neither": float(p[2]),
        "ambiguous_same_bar": float(p[3]),
    }


def load_baseline(path):
    doc = json.loads(Path(path).read_text())
    if doc.get("schema") != "btc-predictive-vnext4r6-baseline-seed-v1":
        raise ValueError("unexpected R6 baseline schema")
    if doc.get("trading_authority") is not False:
        raise ValueError("unexpected trading authority in R6 baseline")
    return doc


def control_prediction(baseline, vol_value, anchor_utc, resolved_records=()):
    control = baseline["control"]
    q0, q1 = map(float, control["vol_quantiles"])
    vol_bin = 0 if float(vol_value) <= q0 else 1 if float(vol_value) <= q1 else 2
    anchor = _parse_utc(anchor_utc)
    start = anchor - timedelta(days=int(control["window_days"]))

    eligible = []
    for record in list(baseline.get("records", ())) + list(resolved_records):
        try:
            a = _parse_utc(record["anchor_utc"])
            due = _parse_utc(record["due_utc"])
            cls = int(record["class_id"])
            vb = int(record["vol_bin"])
        except Exception as ex:
            raise ValueError("malformed R6 baseline record") from ex
        if start <= a < anchor and due < anchor and vb == vol_bin and 0 <= cls <= 3:
            eligible.append(cls)

    frozen = np.asarray(control["training_frequency"], dtype=float)
    if len(eligible) >= int(control["min_same_bin"]):
        counts = np.bincount(np.asarray(eligible, dtype=int), minlength=4).astype(float) + 0.5
        primary = counts / counts.sum()
        source = "vol90d_same_bin"
    else:
        primary = frozen
        source = "frozen_training_frequency_fallback"

    return {
        "primary_name": "vol90d_same_frozen_volatility_bin",
        "primary_distribution": _distribution(primary),
        "primary_source": source,
        "primary_eligible_records": len(eligible),
        "volatility_bin": vol_bin,
        "secondary_name": "frozen_training_frequency",
        "secondary_distribution": _distribution(frozen),
    }
