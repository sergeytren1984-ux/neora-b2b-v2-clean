from datetime import datetime, timezone, timedelta
import json
from pathlib import Path

from barrier import build_barrier_spec, resolve_barrier
from context_trust import factor_status
from model import candle_features, external_features
from selftest import candles, context

protocol = json.loads(Path(__file__).with_name("protocol.json").read_text())
anchor = datetime(2026, 10, 2, 8, tzinfo=timezone.utc)

broken = candles()
broken[-1]["low"] = broken[-1]["high"] + 1
try:
    candle_features(broken)
    raise AssertionError("invalid OHLC accepted")
except ValueError:
    pass

missing = context(omit_external=True)
external = external_features(missing)
assert external["score"] is None and external["used_factors"] == []

future_context = {"factors": {"open_interest": {
    "status": "VALID", "freshness_status": "FRESH", "value_btc": 30000,
    "source_timestamp_utc": (anchor + timedelta(seconds=3)).isoformat(), "age_seconds": -3}}}
assert factor_status(future_context, "open_interest", anchor, protocol)["available"] is False

stale_context = {"factors": {"us10y": {
    "status": "VALID", "freshness_status": "MARKET_CLOSED_LAST_SESSION", "value": 5.2,
    "source_timestamp_utc": (anchor - timedelta(hours=12)).isoformat(), "age_seconds": 43200}}}
assert factor_status(stale_context, "us10y", anchor, protocol)["available"] is False

spec = build_barrier_spec(100.0, 1.0, anchor, protocol)[0]
assert spec["probabilities"] is None
ambiguous = [{"close_time": (anchor + timedelta(hours=1)).isoformat(), "low": 98.0, "high": 102.0}]
assert resolve_barrier(spec, ambiguous, anchor)["class"] == "BOTH_SAME_BAR"

print("REGIME_V3_NEGATIVE_TESTS_OK")
