"""Single 4h arbitration policy: tail warning survives regime disagreement.

No new fitted model, probability calibration, or trade instruction lives here.
"""
from datetime import datetime, timedelta, timezone
import math

UTC = timezone.utc


def decide(directional, regime, *, anchor):
    if anchor.tzinfo is None or anchor.utcoffset() != timedelta(0):
        raise ValueError("anchor must be UTC")
    slot = anchor.strftime("%Y%m%dT%H%M%SZ")
    due = (anchor + timedelta(hours=4)).isoformat()
    if directional.get("type") != "DIRECTIONAL_4H_ALERT_ISSUED":
        raise ValueError("directional event type")
    if regime.get("type") != "REGIME_FORECAST_ISSUED":
        raise ValueError("regime event type")
    if directional.get("slot") != slot or regime.get("slot") != slot:
        raise ValueError("slot mismatch")
    if directional.get("idempotency_key") != "alert:" + slot:
        raise ValueError("directional key mismatch")
    if regime.get("idempotency_key") != "regime:" + slot:
        raise ValueError("regime key mismatch")
    if directional.get("due_utc") != due:
        raise ValueError("directional due mismatch")
    h = regime["output"]["horizons"]["4h"]
    if h.get("due_utc") != due:
        raise ValueError("regime due mismatch")
    dp, rp = float(directional["reference_price"]), float(regime["reference_price"])
    if not all(map(math.isfinite, (dp, rp))) or abs(dp-rp) > 0.01:
        raise ValueError("spot reference price mismatch")
    output = directional["output"]
    rank = float(output["rank_30d"])
    estimate = float(output["candidate_estimate"])
    cutoff = float(output["cutoff_rank"])
    if not all(map(math.isfinite, (rank, estimate, cutoff))) or not (0 <= rank <= 1 and 0 <= estimate <= 1 and cutoff == 0.8):
        raise ValueError("invalid directional numbers")
    alert = output["alert"]
    if type(alert) is not bool or alert != (rank >= cutoff):
        raise ValueError("alert/rank inconsistency")
    if output.get("past_scores_count") != 720:
        raise ValueError("rolling history mismatch")
    scores = h["shadow_class_scores"]
    if set(scores) != {"upside", "range", "downside"}:
        raise ValueError("regime classes mismatch")
    values = [float(scores[k]) for k in ("upside", "range", "downside")]
    if not all(math.isfinite(v) and 0 <= v <= 1 for v in values) or abs(sum(values)-1) > 0.0001:
        raise ValueError("invalid regime shadow scores")
    if h.get("probabilities") is not None or h.get("probability_status") != "UNCALIBRATED_SHADOW_SCORE":
        raise ValueError("regime calibration semantics changed")
    top = max(scores, key=scores.get)
    if list(scores.values()).count(scores[top]) > 1:
        top = "tie"
    state = h.get("regime_state")
    if alert and top == "upside" and state in ("UP_TRANSITION", "UP_CONTINUATION"):
        status = "UPSIDE_TAIL_RISK_CONCORDANT"
    elif alert:
        status = "UPSIDE_TAIL_RISK_WITH_REGIME_DISAGREEMENT"
    elif top == "upside":
        status = "UP_REGIME_UNCONFIRMED"
    elif top == "downside":
        status = "DOWNSIDE_REGIME_UNVALIDATED"
    else:
        status = "NO_DIRECTIONAL_TAIL_WARNING"
    return {"status": status, "action_status": "WATCH_ONLY_NO_TRADE_AUTHORITY" if alert else "NO_DIRECTIONAL_ACTION",
            "slot": slot, "anchor_utc": anchor.isoformat(), "due_utc": due,
            "reference_price": dp, "directional_up_tail_alert": alert,
            "directional_up_tail_candidate_estimate": estimate, "directional_rank_30d": rank,
            "regime_state": state, "regime_4h_top_shadow_class": top,
            "regime_4h_shadow_scores_uncalibrated": scores,
            "reason": "both inputs point upward" if status == "UPSIDE_TAIL_RISK_CONCORDANT" else
                      "upside tail elevated despite unvalidated regime disagreement" if alert else
                      "upside tail not confirmed by the independent head",
            "trading_authority": False}
