"""One-shot, preregistered 2023 test of frozen ±1% 4h tail candidates."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import sys
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from directional_v1.alert import candidate as up_candidate
from directional_down_v1.alert import candidate as down_candidate

UTC = timezone.utc
REPO = "sergeytren1984-ux/neora-b2b-v2-clean"
OUT = "btc_research/untouched_2023_result.json"
BASE = "https://data.binance.vision/data/spot/monthly/klines/BTCUSDT/1h/"


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "btc-untouched-2023-once"})
    with urllib.request.urlopen(req, timeout=45) as response:
        if response.status != 200:
            raise RuntimeError("source HTTP " + str(response.status))
        return response.read()


def archive() -> tuple[list[dict], list[dict]]:
    candles, receipts = [], []
    for month in range(1, 13):
        name = f"BTCUSDT-1h-2023-{month:02d}.zip"
        blob = fetch(BASE + name)
        expected = fetch(BASE + name + ".CHECKSUM").decode().split()[0].lower()
        sha = hashlib.sha256(blob).hexdigest()
        if len(expected) != 64 or sha != expected:
            raise ValueError("official monthly checksum mismatch: " + name)
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            names = z.namelist()
            if names != [name[:-4] + ".csv"]:
                raise ValueError("unexpected archive contents")
            rows = list(csv.reader(io.TextIOWrapper(z.open(names[0]), encoding="utf-8")))
        receipts.append({"url": BASE + name, "sha256": sha, "rows": len(rows)})
        for row in rows:
            if len(row) != 12:
                raise ValueError("unexpected kline columns")
            t = datetime.fromtimestamp(int(row[0]) / 1000, UTC)
            if int(row[6]) != int((t + timedelta(hours=1)).timestamp() * 1000) - 1:
                raise ValueError("invalid close time")
            o, h, l, c, volume, buy = map(float, (row[1], row[2], row[3], row[4], row[5], row[9]))
            trades = int(row[8])
            if (not all(map(math.isfinite, (o, h, l, c, volume, buy))) or
                    min(o, h, l, c) <= 0 or l > min(o, c) or h < max(o, c) or
                    h < l or volume < 0 or not 0 <= buy <= volume or trades < 0):
                raise ValueError("invalid OHLC/activity")
            candles.append({"open_time": t.isoformat(),
                            "close_time": (t + timedelta(hours=1)).isoformat(),
                            "open": o, "high": h, "low": l, "close": c,
                            "volume": volume, "trades": trades, "taker_buy_base": buy})
    if len(candles) != 8760 or any(
            datetime.fromisoformat(b["open_time"]) - datetime.fromisoformat(a["open_time"])
            != timedelta(hours=1) for a, b in zip(candles, candles[1:])):
        raise ValueError("2023 archive has a gap, duplicate or incomplete year")
    return candles, receipts


def metric(truth: np.ndarray, probs: np.ndarray, alert: np.ndarray, dates: list[str]) -> dict:
    prior = float(truth.mean())  # retrospective prevalence shown as a diagnostic, not trained baseline
    n = int(alert.sum())
    weeks = np.array([datetime.fromisoformat(s).strftime("%G-W%V") for s in dates])
    groups = [np.flatnonzero(weeks == week) for week in np.unique(weeks)]
    rng = np.random.default_rng(2023)
    lifts = []
    for _ in range(2000):
        sel = np.concatenate([groups[j] for j in rng.integers(0, len(groups), len(groups))])
        if alert[sel].sum():
            lifts.append(float(truth[sel][alert[sel]].mean() - truth[sel].mean()))
    p = np.clip(probs, 1e-9, 1 - 1e-9)
    return {"n": len(truth), "events": int(truth.sum()),
            "prevalence": prior, "alerts": n,
            "precision": float(truth[alert].mean()) if n else None,
            "recall": float(alert[truth].mean()) if truth.sum() else None,
            "false_alarm_rate": float(alert[~truth].mean()),
            "brier": float(np.mean((p - truth) ** 2)),
            "log_loss": float(np.mean(-(truth * np.log(p) + (1 - truth) * np.log(1 - p)))),
            "retrospective_frequency_brier": float(np.mean((prior - truth) ** 2)),
            "weekly_bootstrap_precision_lift_95ci": np.quantile(lifts, [.025, .975]).tolist()}


def once() -> None:
    headers = {"Authorization": "Bearer " + os.environ["GH_TOKEN"],
               "Accept": "application/vnd.github+json", "User-Agent": "btc-untouched-2023-once"}
    dest = f"https://api.github.com/repos/{REPO}/contents/{OUT}"
    try:
        fetch(dest)  # public repository; existence is a permanent one-shot barrier
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise
    else:
        raise RuntimeError("untouched block already opened; refuse to overwrite")
    cs, receipts = archive()
    root = Path(__file__).resolve().parents[1]
    artifacts = {name: json.loads((root / path).read_bytes()) for name, path in (
        ("up", "directional_v1/artifact.json"), ("down", "directional_down_v1/artifact.json"))}
    estimates = {name: [] for name in artifacts}
    for i in range(168, len(cs)):
        bars = cs[i-168:i+1]
        estimates["up"].append(up_candidate(bars, artifacts["up"])[0])
        estimates["down"].append(down_candidate(bars, artifacts["down"])[0])
    results = {}
    start = 168 + 720
    dates = [cs[i]["close_time"] for i in range(start, len(cs)-4)]
    for name, sign in (("up", 1), ("down", -1)):
        scores = np.array(estimates[name])
        idx = np.arange(start, len(cs)-4)
        rank = np.array([np.mean(scores[i-168-720:i-168] <= scores[i-168]) for i in idx])
        alert = rank >= .8
        truth = np.array([100 * sign * (cs[i+4]["close"] / cs[i]["close"] - 1) > 1 for i in idx])
        results[name] = metric(truth, scores[idx-168], alert, dates)
    result = {"schema": "btc-untouched-2023-one-shot-v1", "target": "BTCUSDT spot ±1% 4h close",
              "period": "2023-01-01 through 2023-12-31 UTC",
              "candidate_frozen_before_archive_opened": "2026-10-03T07:27:14Z",
              "training_2024_2025_only": True, "warning_cutoff_rank": .8,
              "first_720_scores_warmup_only": True, "archive_receipts": receipts,
              "artifacts_sha256": {name: hashlib.sha256((root / path).read_bytes()).hexdigest()
                                   for name, path in (("up", "directional_v1/artifact.json"),
                                                      ("down", "directional_down_v1/artifact.json"))},
              "results": results, "trading_authority": False,
              "interpretation": "one historical stress block; prospective still required"}
    payload = json.dumps(result, sort_keys=True, indent=2) + "\n"
    import base64
    body = {"message": "Seal one-shot untouched 2023 BTC directional result",
            "branch": "main", "content": base64.b64encode(payload.encode()).decode()}
    req = urllib.request.Request(dest, data=json.dumps(body).encode(), headers=headers, method="PUT")
    with urllib.request.urlopen(req, timeout=30) as response:
        if response.status != 201:
            raise RuntimeError("one-shot result publication failed")
    print("UNTOUCHED_2023_SEALED", results, flush=True)


if __name__ == "__main__":
    once()
