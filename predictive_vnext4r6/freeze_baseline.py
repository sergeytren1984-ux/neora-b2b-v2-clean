"""Build deterministic pre-start adaptive baseline seeds for vNext4R6.

The prospective control is the same volatility-bin 90-day baseline used by the
historical structural benchmark. Quantile boundaries and fallback frequencies are
computed only from the fixed historical training partition. Seed outcomes are
constructed only from candles whose full outcome horizon is already closed before
the freeze instant.

This script grants no production or trading authority.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import math
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from predictive_vnext4.core import (
    read_klines,
    build_15m_features,
    build_hourly_features,
    target_distance,
    masks,
)

UTC = timezone.utc
ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / "predictive_vnext4r6"
RESEARCH = ROOT / "research_vnext4r6"

HISTORY_DAYS = {"15m": 130, "1h": 160}
INTERVAL_MS = {"15m": 900000, "1h": 3600000}
MIN_SAME_BIN = 30
WINDOW_DAYS = 90


def canonical(obj):
    return (json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def fetch_recent(interval, freeze_now):
    duration_ms = INTERVAL_MS[interval]
    days = HISTORY_DAYS[interval]
    start = int((freeze_now - timedelta(days=days)).timestamp() * 1000)
    end = int(freeze_now.timestamp() * 1000) - 1
    rows = []
    cursor = start
    while cursor <= end:
        params = urllib.parse.urlencode({
            "symbol": "BTCUSDT",
            "interval": interval,
            "startTime": cursor,
            "endTime": end,
            "limit": 1000,
        })
        req = urllib.request.Request(
            "https://data-api.binance.vision/api/v3/klines?" + params,
            headers={"User-Agent": "btc-predictive-vnext4r6-baseline-freeze"},
        )
        with urllib.request.urlopen(req, timeout=35) as response:
            batch = json.loads(response.read())
        if not batch:
            break
        rows.extend(batch)
        nxt = int(batch[-1][0]) + duration_ms
        if nxt <= cursor:
            raise RuntimeError("recent-history cursor did not advance")
        cursor = nxt
        if len(batch) < 1000:
            break

    cutoff_ms = int(freeze_now.timestamp() * 1000)
    uniq = {
        int(r[0]): r
        for r in rows
        if int(r[6]) < cutoff_ms
    }
    rows = [uniq[k] for k in sorted(uniq)]
    if len(rows) < 500:
        raise RuntimeError(f"insufficient {interval} baseline source rows")
    if any(int(b[0]) - int(a[0]) != duration_ms for a, b in zip(rows, rows[1:])):
        raise ValueError(f"{interval} recent source gap/duplicate")
    if any(int(r[6]) != int(r[0]) + duration_ms - 1 for r in rows):
        raise ValueError(f"{interval} partial candle")
    return rows


def arrays(rows):
    t = np.asarray([int(r[0]) for r in rows], dtype=np.int64)
    hi = np.asarray([float(r[2]) for r in rows])
    lo = np.asarray([float(r[3]) for r in rows])
    c = np.asarray([float(r[4]) for r in rows])
    v = np.asarray([float(r[5]) for r in rows])
    trades = np.asarray([float(r[8]) for r in rows])
    taker = np.asarray([float(r[9]) for r in rows])
    return t, hi, lo, c, v, trades, taker


def class_control(y, vol, train):
    counts = np.bincount(y[train], minlength=4).astype(float) + 0.5
    q = np.quantile(vol[train], [1 / 3, 2 / 3])
    return {
        "training_frequency": (counts / counts.sum()).tolist(),
        "vol_quantiles": [float(q[0]), float(q[1])],
        "window_days": WINDOW_DAYS,
        "min_same_bin": MIN_SAME_BIN,
        "fallback": "frozen_training_frequency",
    }


def records(dates, y, vol, control, due_delta, freeze_now):
    q = np.asarray(control["vol_quantiles"], dtype=float)
    bins = np.digitize(vol, q, right=True)
    freeze = np.datetime64(freeze_now.replace(tzinfo=None))
    lower = freeze - np.timedelta64(HISTORY_DAYS["15m"] + 10, "D")
    out = []
    for anchor, cls, vb in zip(dates, y, bins):
        due = anchor + due_delta
        if due >= freeze or anchor < lower:
            continue
        out.append({
            "anchor_utc": str(anchor.astype("datetime64[s]")) + "Z",
            "due_utc": str(due.astype("datetime64[s]")) + "Z",
            "class_id": int(cls),
            "vol_bin": int(vb),
        })
    return out


def training_control_15m(bars):
    path = RESEARCH / "data" / "BTCUSDT_15m_2024-01_2026-09.json.gz"
    t, o, hi, lo, c, v, trades, taker, source_sha = read_klines(path, 900000)
    ix, dates, X, names, regime, vol = build_15m_features(t, hi, lo, c, v, trades, taker, 16)
    distance = c[ix] * vol * np.sqrt(float(bars))
    y, when = target_distance(ix, c, hi, lo, distance, bars)
    train, _, _ = masks(
        dates, np.timedelta64(bars * 15, "m"),
        "2026-01-01", "2026-01-01", "2026-07-01",
        "2026-07-08", "2026-09-24",
    )
    return class_control(y, vol, train), source_sha


def training_control_24h():
    path = ROOT / "btc_1h_2024_to_sep24_2026.json"
    t, o, hi, lo, c, v, trades, taker, source_sha = read_klines(path, 3600000)
    ix, dates, X, names, regime, vol, atr = build_hourly_features(t, hi, lo, c, v, trades, taker, 24)
    distance = c[ix] * vol * np.sqrt(24.0)
    y, when = target_distance(ix, c, hi, lo, distance, 24)
    train, _, _ = masks(
        dates, np.timedelta64(24, "h"),
        "2026-01-01", "2026-01-01", "2026-07-01",
        "2026-07-08", "2026-09-24",
    )
    return class_control(y, vol, train), source_sha


def live_seed_15m(rows, bars, control, freeze_now):
    t, hi, lo, c, v, trades, taker = arrays(rows)
    ix, dates, X, names, regime, vol = build_15m_features(t, hi, lo, c, v, trades, taker, 16)
    distance = c[ix] * vol * np.sqrt(float(bars))
    y, when = target_distance(ix, c, hi, lo, distance, bars)
    return records(dates, y, vol, control, np.timedelta64(bars * 15, "m"), freeze_now)


def live_seed_24h(rows, control, freeze_now):
    t, hi, lo, c, v, trades, taker = arrays(rows)
    ix, dates, X, names, regime, vol, atr = build_hourly_features(t, hi, lo, c, v, trades, taker, 24)
    distance = c[ix] * vol * np.sqrt(24.0)
    y, when = target_distance(ix, c, hi, lo, distance, 24)
    return records(dates, y, vol, control, np.timedelta64(24, "h"), freeze_now)


def write_json(path, obj):
    raw = canonical(obj)
    path.write_bytes(raw)
    return {"sha256": sha(raw), "records": len(obj.get("records", []))}


def main():
    freeze_now = datetime.now(UTC)
    recent15 = fetch_recent("15m", freeze_now)
    recent1h = fetch_recent("1h", freeze_now)

    controls = {}
    ctrl1, hist15sha = training_control_15m(4)
    ctrl4, hist15sha_b = training_control_15m(16)
    if hist15sha != hist15sha_b:
        raise RuntimeError("15m historical source hash drift")
    ctrl24, hist1hsha = training_control_24h()
    controls["1h"] = ctrl1
    controls["4h"] = ctrl4
    controls["24h"] = ctrl24

    docs = {
        "1h": {
            "schema": "btc-predictive-vnext4r6-baseline-seed-v1",
            "head": "1h",
            "freeze_utc": freeze_now.isoformat(),
            "control": ctrl1,
            "records": live_seed_15m(recent15, 4, ctrl1, freeze_now),
            "trading_authority": False,
        },
        "4h": {
            "schema": "btc-predictive-vnext4r6-baseline-seed-v1",
            "head": "4h",
            "freeze_utc": freeze_now.isoformat(),
            "control": ctrl4,
            "records": live_seed_15m(recent15, 16, ctrl4, freeze_now),
            "trading_authority": False,
        },
        "24h": {
            "schema": "btc-predictive-vnext4r6-baseline-seed-v1",
            "head": "24h",
            "freeze_utc": freeze_now.isoformat(),
            "control": ctrl24,
            "records": live_seed_24h(recent1h, ctrl24, freeze_now),
            "trading_authority": False,
        },
    }

    files = {}
    for head, doc in docs.items():
        p = HERE / f"baseline_{head}.json"
        files[head] = {
            "path": str(p.relative_to(ROOT)),
            **write_json(p, doc),
        }

    source15 = canonical({"interval": "15m", "rows": recent15})
    source1h = canonical({"interval": "1h", "rows": recent1h})
    metadata = {
        "schema": "btc-predictive-vnext4r6-baseline-freeze-metadata-v1",
        "freeze_utc": freeze_now.isoformat(),
        "baseline": "vol90d_same_frozen_volatility_bin",
        "history_window_days": WINDOW_DAYS,
        "minimum_same_bin_records": MIN_SAME_BIN,
        "training_partition": "labels due before 2026-01-01 UTC",
        "historical_training_sources": {
            "15m_sha256": hist15sha,
            "1h_sha256": hist1hsha,
        },
        "recent_source_logical_sha256": {
            "15m": sha(source15),
            "1h": sha(source1h),
        },
        "recent_source_rows": {
            "15m": len(recent15),
            "1h": len(recent1h),
        },
        "files": files,
        "predictive_accept": False,
        "prospective_admission": False,
        "trading_authority": False,
    }
    write_json(HERE / "baseline_metadata.json", metadata)
    print(json.dumps(metadata, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
