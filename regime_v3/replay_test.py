"""Frozen diagnostic replay cases; these are not an independent performance holdout."""

from datetime import datetime, timezone, timedelta
import json
from pathlib import Path

from model import forecast
from selftest import context


def synthetic_breakout_path():
    out, price = [], 83000.0
    start = datetime(2026, 9, 25, tzinfo=timezone.utc)
    for i in range(169):
        previous = price
        if i < 156:
            step = 0.00002 if i % 2 else -0.00002
        elif i == 156:
            step = 0.009
        else:
            step = 0.00045 if i % 3 else -0.00010
        price *= 1.0 + step
        volume = 900.0 if i < 156 else 1550.0
        out.append({"open_time": (start + timedelta(hours=i)).isoformat(),
                    "close_time": (start + timedelta(hours=i + 1)).isoformat(),
                    "open": previous, "high": max(previous, price) * 1.0012,
                    "low": min(previous, price) * 0.9988, "close": price,
                    "volume": volume, "trades": 9000 if i < 156 else 15000,
                    "taker_buy_base": volume * (0.50 if i < 156 else 0.57)})
    return out


protocol = json.loads(Path(__file__).with_name("protocol.json").read_text())
path = synthetic_breakout_path()
output = forecast(path, context(True), protocol)
assert output["regime_state"] in {"UP_TRANSITION", "UP_CONTINUATION", "UP_EXHAUSTION"}
assert output["features"]["breakout_memory"]["retention"] > 0
assert output["horizons"]["4h"]["probabilities"]["upside"] > output["horizons"]["4h"]["probabilities"]["downside"]
print("REGIME_V3_REPLAY_DIAGNOSTIC_OK")
