from datetime import datetime, timezone, timedelta
import json
from pathlib import Path

from barrier import build_barrier_spec, resolve_barrier
from model import forecast


def candles(direction=0.0, breakout=False, fail=False):
    out, price = [], 84000.0
    start = datetime(2026, 9, 20, tzinfo=timezone.utc)
    for i in range(169):
        previous = price
        step = direction
        if breakout and i == 158:
            step = 0.009
        elif breakout and i > 158:
            step = 0.00025
        if fail and i >= 164:
            step = -0.0022
        price *= 1.0 + step
        volume = 1000 + (i % 7) * 25
        out.append({"open_time": (start + timedelta(hours=i)).isoformat(),
                    "close_time": (start + timedelta(hours=i + 1)).isoformat(),
                    "open": previous, "high": max(previous, price) * 1.0015,
                    "low": min(previous, price) * 0.9985, "close": price,
                    "volume": volume, "trades": 10000 + i % 11 * 70,
                    "taker_buy_base": volume * (0.56 if step > 0 else 0.44 if step < 0 else 0.50)})
    return out


def context(bull=True, omit_external=False):
    now = datetime(2026, 10, 2, 8, tzinfo=timezone.utc)
    before = now - timedelta(hours=1)
    old = {"captured_at_utc": before.isoformat(), "factors": {
        "open_interest": {"status": "VALID", "value_btc": 29000},
        "funding": {"status": "VALID", "value": 0.00004},
        "dxy": {"status": "VALID", "value": 102.1},
        "nasdaq_futures": {"status": "VALID", "value": 30700},
        "us10y": {"status": "VALID", "value": 5.30},
        "etf_flows": {"status": "VALID", "numeric_value": 0}}}
    new = {"captured_at_utc": now.isoformat(), "factors": {
        "open_interest": {"status": "VALID", "value_btc": 30000},
        "funding": {"status": "VALID", "value": 0.00005},
        "dxy": {"status": "VALID", "value": 101.8 if bull else 102.4},
        "nasdaq_futures": {"status": "VALID", "value": 31000 if bull else 30400},
        "us10y": {"status": "VALID", "value": 5.20 if bull else 5.40},
        "etf_flows": {"status": "VALID", "numeric_value": 180 if bull else -180}}}
    keys = ("open_interest", "funding", "dxy", "nasdaq_futures", "us10y", "etf_flows")
    status = {key: {"available": not omit_external} for key in keys}
    return {"current": new, "previous": old, "elapsed_seconds": 3600,
            "current_factor_status": status, "previous_factor_status": status,
            "snapshot_names": ["now", "before"], "legacy_numeric_challenger_authorized": False}


protocol = json.loads(Path(__file__).with_name("protocol.json").read_text())
assert abs(sum(protocol["regime_formula"].values()) - 1.0) < 1e-12
for weights in protocol["horizon_formula"].values():
    assert abs(sum(weights.values()) - 1.0) < 1e-12

bull = forecast(candles(0.0008), context(True), protocol)
bear = forecast(candles(-0.0008), context(False), protocol)
flat = forecast(candles(0.0), context(True, omit_external=True), protocol)
held_breakout = forecast(candles(0.0, breakout=True), context(True), protocol)
failed_breakout = forecast(candles(0.0, breakout=True, fail=True), context(False), protocol)

assert bull["regime_score"] > 0 and bull["regime_state"].startswith("UP_")
assert bear["regime_score"] < 0 and bear["regime_state"].startswith("DOWN_")
assert flat["external"]["score"] is None
assert "external_market" not in flat["components_used"]
assert held_breakout["features"]["breakout_memory"]["direction"] == 1
assert held_breakout["features"]["breakout_memory"]["retention"] > 0
assert failed_breakout["features"]["false_breakout"] > 0

for output in (bull, bear, flat, held_breakout, failed_breakout):
    assert output["probability_status"] == "UNCALIBRATED_SHADOW_SCORE"
    for horizon in ("1h", "4h", "24h"):
        probabilities = output["horizons"][horizon]["probabilities"]
        assert set(probabilities) == {"upside", "range", "downside"}
        assert abs(sum(probabilities.values()) - 1.0) < 1e-10
        assert output["horizons"][horizon]["threshold_pct"] > 0

anchor = datetime(2026, 10, 2, 8, tzinfo=timezone.utc)
spec = build_barrier_spec(100.0, 1.0, anchor, protocol)[0]
assert spec["probabilities"] is None and spec["probability_status"] == "WITHHELD_UNTIL_CALIBRATED"
same_bar = [{"close_time": (anchor + timedelta(hours=1)).isoformat(), "low": 98.0, "high": 102.0}]
assert resolve_barrier(spec, same_bar, anchor)["class"] == "BOTH_SAME_BAR"
print("REGIME_V3_EXPERT_SELFTEST_OK")
