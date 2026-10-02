from __future__ import annotations

import math

CLASSES = ("upside", "range", "downside")


def clip(x, a=-1.0, b=1.0):
    return max(a, min(b, float(x)))


def pct(a, b):
    return 100.0 * (float(a) / float(b) - 1.0) if float(b) else 0.0


def softmax(up, rg, dn):
    m = max(up, rg, dn)
    ex = [math.exp(x - m) for x in (up, rg, dn)]
    total = sum(ex)
    return {"upside": ex[0] / total, "range": ex[1] / total, "downside": ex[2] / total}


def _ema(values, span):
    alpha = 2.0 / (span + 1.0)
    out = float(values[0])
    for value in values[1:]:
        out = alpha * float(value) + (1.0 - alpha) * out
    return out


def _signed_efficiency(values, window):
    x = values[-(window + 1):]
    path = sum(abs(x[i] - x[i - 1]) for i in range(1, len(x)))
    return 0.0 if path == 0 else clip((x[-1] - x[0]) / path)


def _breakout_memory(close, high, low, atr_abs, lookback=18):
    """Reconstruct the latest breakout deterministically from closed candles."""
    candidates = []
    start = max(24, len(close) - lookback)
    for i in range(start, len(close)):
        prior_high = max(high[i - 24:i])
        prior_low = min(low[i - 24:i])
        if close[i] > prior_high:
            candidates.append((i, 1, prior_high, (close[i] - prior_high) / atr_abs))
        if close[i] < prior_low:
            candidates.append((i, -1, prior_low, (prior_low - close[i]) / atr_abs))
    if not candidates:
        return {"direction": 0, "age_hours": None, "level": None, "initial_strength": 0.0,
                "hold_atr": 0.0, "retention": 0.0, "false_breakout": 0.0}
    i, direction, level, initial = candidates[-1]
    age = len(close) - 1 - i
    hold = direction * (close[-1] - level) / atr_abs
    retention = direction * clip((hold + 0.40) / 1.00, 0.0, 1.0) * math.exp(-age / 30.0)
    failure = clip((-hold - 0.10) / 0.75, 0.0, 1.0)
    return {"direction": direction, "age_hours": age, "level": level,
            "initial_strength": clip(initial, 0.0, 2.0), "hold_atr": hold,
            "retention": retention, "false_breakout": direction * failure}


def candle_features(candles):
    if len(candles) < 169:
        raise ValueError("169 closed 1h candles required")
    candles = candles[-169:]
    close = [float(x["close"]) for x in candles]
    high = [float(x["high"]) for x in candles]
    low = [float(x["low"]) for x in candles]
    volume = [float(x["volume"]) for x in candles]
    taker = [float(x["taker_buy_base"]) for x in candles]
    trades = [float(x["trades"]) for x in candles]
    for i, x in enumerate(candles):
        o, h, l, c = map(float, (x["open"], x["high"], x["low"], x["close"]))
        if l > min(o, c) or h < max(o, c) or h < l:
            raise ValueError(f"OHLC invariant failed at {i}")
        if float(x["volume"]) < 0 or int(x["trades"]) < 0:
            raise ValueError("negative market activity")

    ret = lambda n: pct(close[-1], close[-1 - n])
    true_ranges = []
    for i in range(len(candles) - 24, len(candles)):
        previous = close[i - 1]
        true_ranges.append(max(high[i] - low[i], abs(high[i] - previous), abs(low[i] - previous)))
    atr_abs = max(sum(true_ranges) / len(true_ranges), close[-1] * 0.0005)
    atr_pct = 100.0 * atr_abs / close[-1]

    def imbalance(window):
        den = sum(volume[-window:])
        return 0.0 if den <= 0 else sum(2.0 * taker[i] - volume[i] for i in range(len(candles) - window, len(candles))) / den

    def log_z(values, window):
        x = [math.log1p(max(0.0, value)) for value in values[-window:]]
        mean = sum(x) / len(x)
        sd = math.sqrt(sum((value - mean) ** 2 for value in x) / len(x))
        return 0.0 if sd == 0 else (x[-1] - mean) / sd

    pos6 = sum(close[i] > close[i - 1] for i in range(len(close) - 6, len(close))) / 6.0
    hh6 = sum(high[i] > high[i - 1] for i in range(len(high) - 6, len(high))) / 6.0
    hl6 = sum(low[i] > low[i - 1] for i in range(len(low) - 6, len(low))) / 6.0
    lh6 = sum(high[i] < high[i - 1] for i in range(len(high) - 6, len(high))) / 6.0
    ll6 = sum(low[i] < low[i - 1] for i in range(len(low) - 6, len(low))) / 6.0
    previous_24_high, previous_24_low = max(high[-25:-1]), min(low[-25:-1])
    previous_72_high, previous_72_low = max(high[-73:-1]), min(low[-73:-1])
    break_up_24 = (close[-1] - previous_24_high) / atr_abs
    break_down_24 = (previous_24_low - close[-1]) / atr_abs
    break_up_72 = (close[-1] - previous_72_high) / atr_abs
    break_down_72 = (previous_72_low - close[-1]) / atr_abs

    ema6 = _ema(close[-48:], 6)
    ema12 = _ema(close[-72:], 12)
    ema24 = _ema(close[-120:], 24)
    ema_alignment = clip(((ema6 - ema12) + 0.6 * (ema12 - ema24)) / atr_abs / 2.0)
    efficiency6 = _signed_efficiency(close, 6)
    efficiency12 = _signed_efficiency(close, 12)
    efficiency24 = _signed_efficiency(close, 24)
    trend_quality = clip(0.25 * efficiency6 + 0.40 * efficiency12 + 0.35 * efficiency24)

    technical = clip(0.16 * math.tanh(ret(3) / (1.2 * atr_pct))
                     + 0.22 * math.tanh(ret(6) / (1.8 * atr_pct))
                     + 0.22 * math.tanh(ret(12) / (2.8 * atr_pct))
                     + 0.18 * math.tanh(ret(24) / (4.0 * atr_pct))
                     + 0.12 * (2.0 * pos6 - 1.0) + 0.10 * ema_alignment)
    structure = clip(0.35 * math.tanh(max(0.0, break_up_24))
                     + 0.15 * math.tanh(max(0.0, break_up_72))
                     - 0.35 * math.tanh(max(0.0, break_down_24))
                     - 0.15 * math.tanh(max(0.0, break_down_72))
                     + 0.15 * ((hl6 + hh6) - (ll6 + lh6)))
    flow = clip(0.45 * clip(imbalance(1) * 3.0) + 0.30 * clip(imbalance(4) * 3.0)
                + 0.125 * clip(log_z(volume, 24) / 3.0) + 0.125 * clip(log_z(trades, 24) / 3.0))

    log_returns = [math.log(close[i] / close[i - 1]) for i in range(len(close) - 48, len(close))]
    mean = sum(log_returns) / len(log_returns)
    sd = math.sqrt(sum((x - mean) ** 2 for x in log_returns) / len(log_returns)) or 1e-9
    positive = negative = 0.0
    for value in log_returns[-12:]:
        zret = (value - mean) / sd
        positive = max(0.0, positive + zret - 0.25)
        negative = max(0.0, negative - zret - 0.25)
    change_point = clip((positive - negative) / 3.0)

    transition = clip(ret(6) / (atr_pct * 2.2))
    immediate_breakout = clip(max(0.0, break_up_24) - max(0.0, break_down_24))
    memory = _breakout_memory(close, high, low, atr_abs)
    breakout_state = clip(0.45 * immediate_breakout + 0.55 * memory["retention"])
    persistence = clip(0.45 * trend_quality + 0.35 * ema_alignment + 0.20 * (2.0 * pos6 - 1.0))
    memory_direction = int(memory["direction"])
    trend_confirmation = clip(memory_direction * trend_quality / 0.30, 0.0, 1.0)
    ema_confirmation = clip(memory_direction * ema_alignment / 0.30, 0.0, 1.0)
    confirmed_breakout = memory_direction * abs(memory["retention"]) * trend_confirmation * ema_confirmation
    stretch = (close[-1] - ema24) / atr_abs
    last_reversal = (-math.copysign(1.0, stretch) * clip(abs(ret(1)) / max(atr_pct, 1e-9), 0.0, 1.0)
                     if ret(1) * stretch < 0 else 0.0)
    exhaustion = math.copysign(clip((abs(stretch) - 2.2) / 2.0, 0.0, 1.0), stretch if stretch else 1.0)
    exhaustion = clip(exhaustion + 0.35 * last_reversal)

    return {"technical": technical, "structure": structure, "flow": flow, "transition": transition,
            "breakout": breakout_state, "persistence": persistence, "change_point": change_point,
            "trend_quality": trend_quality, "ema_alignment": ema_alignment, "exhaustion": exhaustion,
            "false_breakout": memory["false_breakout"], "confirmed_breakout": confirmed_breakout,
            "breakout_memory": memory,
            "ret_1h": ret(1), "ret_3h": ret(3), "ret_6h": ret(6), "ret_12h": ret(12),
            "ret_24h": ret(24), "atr24_pct": atr_pct, "taker_imbalance_1h": imbalance(1),
            "taker_imbalance_4h": imbalance(4), "stretch_from_ema24_atr": stretch}


def _value(context, name, key):
    value = ((context.get("factors") or {}).get(name, {})).get(key)
    return float(value) if isinstance(value, (int, float)) else None


def external_features(pair):
    current, previous = pair["current"], pair["previous"]
    elapsed = float(pair["elapsed_seconds"])
    if elapsed <= 0:
        raise ValueError("elapsed context time invalid")
    hour_scale = 3600.0 / elapsed
    current_status, previous_status = pair["current_factor_status"], pair["previous_factor_status"]
    signals, details = [], {}

    def available(name):
        return current_status.get(name, {}).get("available") and previous_status.get(name, {}).get("available")

    if available("open_interest"):
        now, before = _value(current, "open_interest", "value_btc"), _value(previous, "open_interest", "value_btc")
        if now is not None and before not in (None, 0):
            change = pct(now, before) * hour_scale
            direction = 1 if pair.get("price_ret_1h", 0) > 0 else -1 if pair.get("price_ret_1h", 0) < 0 else 0
            confirmation = math.tanh(abs(change) / 1.5) * direction
            if change < 0:
                confirmation *= -0.5
            signals.append(("open_interest", 0.34, confirmation))
            details["oi_change_pct_per_hour"] = change
    if current_status.get("funding", {}).get("available"):
        raw = _value(current, "funding", "value")
        if raw is not None:
            funding, crowding = 100.0 * raw, 0.0
            if funding > 0.015:
                crowding = -math.tanh((funding - 0.015) / 0.02)
            elif funding < -0.015:
                crowding = math.tanh((-funding - 0.015) / 0.02)
            signals.append(("funding", 0.14, crowding))
            details.update({"funding_pct": funding, "funding_crowding": crowding})

    def index_signal(name, weight, scale, sign=1.0):
        if not available(name):
            return
        now, before = _value(current, name, "value"), _value(previous, name, "value")
        if now is None or before in (None, 0):
            return
        change = pct(now, before) * hour_scale
        signals.append((name, weight, clip(sign * change / scale)))
        details[name + "_change_pct_per_hour"] = change

    index_signal("dxy", 0.18, 0.35, -1.0)
    index_signal("nasdaq_futures", 0.16, 0.8, 1.0)
    if available("us10y"):
        now, before = _value(current, "us10y", "value"), _value(previous, "us10y", "value")
        if now is not None and before is not None:
            bps = (now - before) * 100.0 * hour_scale
            signals.append(("us10y", 0.10, clip(-bps / 12.0)))
            details["us10y_change_bps_per_hour"] = bps
    if current_status.get("etf_flows", {}).get("available"):
        etf = _value(current, "etf_flows", "numeric_value")
        if etf is not None:
            signals.append(("etf_flows", 0.08, math.tanh(etf / 250.0)))
            details["etf_usd_m"] = etf
    if not signals:
        return {"score": None, "available_weight": 0.0, "used_factors": [], "details": details}
    total = sum(weight for _, weight, _ in signals)
    return {"score": clip(sum(weight * value for _, weight, value in signals) / total),
            "available_weight": total, "used_factors": [name for name, _, _ in signals], "details": details}


def _weighted_score(features, external, weights):
    components = {"technical": features["technical"], "structure": features["structure"],
                  "market_microstructure": features["flow"], "transition": features["transition"],
                  "breakout": features["breakout"], "persistence": features["persistence"],
                  "change_point": features["change_point"], "trend_quality": features["trend_quality"],
                  "external_market": external["score"]}
    used = {name: value for name, value in components.items() if value is not None and weights.get(name, 0) > 0}
    denominator = sum(weights[name] for name in used)
    if denominator <= 0:
        raise ValueError("no usable score components")
    return clip(sum(weights[name] * value for name, value in used.items()) / denominator), used


def _state_label(score, features):
    false_breakout = features["false_breakout"]
    if abs(false_breakout) >= 0.55:
        return "FALSE_BREAKOUT_UP" if false_breakout > 0 else "FALSE_BREAKOUT_DOWN"
    memory = features["breakout_memory"]
    memory_direction = int(memory["direction"])
    memory_held = (memory_direction != 0 and memory["age_hours"] is not None
                   and memory["age_hours"] <= 18 and memory["hold_atr"] > -0.10)
    if abs(score) < 0.14 and not (memory_held and memory_direction * score >= 0.08):
        return "RANGE"
    direction = 1 if score > 0 else -1
    exhaustion = direction * features["exhaustion"]
    age = memory["age_hours"]
    fresh = age is not None and age <= 3 and direction == memory_direction
    if exhaustion >= 0.55:
        return "UP_EXHAUSTION" if direction > 0 else "DOWN_EXHAUSTION"
    if fresh and direction * features["transition"] > 0.35:
        return "UP_TRANSITION" if direction > 0 else "DOWN_TRANSITION"
    return "UP_CONTINUATION" if direction > 0 else "DOWN_CONTINUATION"


def horizon_outputs(features, external, protocol):
    outputs = {}
    atr = features["atr24_pct"]
    thresholds = {"1h": max(0.12, 0.55 * atr), "4h": max(0.25, 1.20 * atr), "24h": max(0.60, 2.20 * atr)}
    for horizon in ("1h", "4h", "24h"):
        score, used = _weighted_score(features, external, protocol["horizon_formula"][horizon])
        memory = features["confirmed_breakout"]
        score = clip(score + protocol["breakout_memory_score_boost"][horizon] * memory)
        same_direction_exhaustion = math.copysign(1.0, score if score else 1.0) * features["exhaustion"]
        score = clip(score - protocol["exhaustion_penalty"][horizon] * same_direction_exhaustion)
        mapping = protocol["probability_mapping"][horizon]
        temperature = mapping["temperature"]
        probabilities = softmax(mapping["direction_scale"] * score / temperature,
                                (mapping["range_bias"] - mapping["range_penalty"] * abs(score)
                                 - mapping["confirmed_breakout_range_penalty"] * abs(memory)) / temperature,
                                -mapping["direction_scale"] * score / temperature)
        outputs[horizon] = {"score": score, "used_components": sorted(used), "probabilities": probabilities,
                            "probability_status": "UNCALIBRATED_SHADOW_SCORE", "threshold_pct": thresholds[horizon]}
    return outputs


def forecast(candles, context_pair, protocol):
    features = candle_features(candles)
    context_pair = dict(context_pair)
    context_pair["price_ret_1h"] = features["ret_1h"]
    external = external_features(context_pair)
    score, used = _weighted_score(features, external, protocol["regime_formula"])
    state = _state_label(score, features)
    regime_probabilities = softmax(2.6 * score / 1.7, (1.55 - 1.75 * abs(score)) / 1.7, -2.6 * score / 1.7)
    return {"schema": "btc-regime-v4-shadow-output-v1", "regime_score": score, "regime_state": state,
            "regime_probabilities": regime_probabilities, "probability_status": "UNCALIBRATED_SHADOW_SCORE",
            "components_used": sorted(used),
            "components": {name: features[name] for name in ("technical", "structure", "flow", "transition",
                "breakout", "persistence", "change_point", "trend_quality", "ema_alignment", "exhaustion",
                "false_breakout", "confirmed_breakout")},
            "external": external, "macro": {"status": "DISABLED_PENDING_TIMESTAMPED_CALIBRATION", "score": None},
            "horizons": horizon_outputs(features, external, protocol), "features": features,
            "calibration_status": "PROSPECTIVE_VALIDATION_REQUIRED", "trading_authority": False}
