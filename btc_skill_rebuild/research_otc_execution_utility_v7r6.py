"""v7R6 MATHEMATICAL utility: NOW request at t vs WAIT request at t+60m.

Prices are at operator execution t+60 and t+120, not publication t.
This research calculator cannot verify receipts or actual counterfactual fills.
It never grants trading authority or claims prospective forecast quality.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import isfinite, sqrt
from statistics import mean, stdev
from typing import Optional, Sequence

UTC=timezone.utc
CAPITAL_USDT=147600.
OTC_MARKUP_MIN=300.
OTC_MARKUP_MAX=400.
FILL_NOW_MINUTES=60
FILL_WAIT_MINUTES=120

@dataclass(frozen=True)
class Quote:
    time_utc: datetime
    ask_usdt_per_btc: float
    status: str # firm_available, indicative, rejected, missing
    source: str # operator, spot_proxy
    firm_capacity_usdt: Optional[float]=None

@dataclass(frozen=True)
class Prediction:
    slot_utc: datetime
    public_time_utc: datetime
    expected_wait_advantage_btc: float
    source_sha256: str

def utc(value):
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("unaware observation time")
    return value.astimezone(UTC)

def _quote_usable(q, scheduled_time, tolerance_minutes, capital):
    if q.source not in ("operator","spot_proxy"):
        raise ValueError("unknown quote source")
    if q.status not in ("firm_available","indicative","rejected","missing"):
        raise ValueError("unknown quote status")
    if not isfinite(q.ask_usdt_per_btc) or q.ask_usdt_per_btc<=0:
        if q.status not in ("missing","rejected"):
            raise ValueError("invalid ask")
        return False,q.status
    if abs((utc(q.time_utc)-scheduled_time).total_seconds())>60*tolerance_minutes:
        return False,"execution_time_mismatch"
    if q.status!="firm_available":
        return False,q.status
    if q.source=="operator" and (q.firm_capacity_usdt is None or
        not isfinite(q.firm_capacity_usdt) or q.firm_capacity_usdt<capital):
        return False,"firm_capacity_not_confirmed"
    return True,"conditional_quote"

def paired_economic_outcome(prediction,now,wait,*,capital=CAPITAL_USDT,
                             timestamp_tolerance_minutes=5):
    t=utc(prediction.slot_utc)
    public=utc(prediction.public_time_utc)
    if not (isfinite(capital) and capital>0):
        raise ValueError("invalid capital")
    if not t<=public<t+timedelta(minutes=FILL_NOW_MINUTES):
        raise ValueError("forecast not published before first execution")
    if not isfinite(prediction.expected_wait_advantage_btc):
        raise ValueError("invalid model expectation")
    if len(prediction.source_sha256)!=64 or any(
        c not in "0123456789abcdef" for c in prediction.source_sha256):
        raise ValueError("exact frozen SHA required")
    first,reason_now=_quote_usable(now,t+timedelta(minutes=60),
                                    timestamp_tolerance_minutes,capital)
    second,reason_wait=_quote_usable(wait,t+timedelta(minutes=120),
                                     timestamp_tolerance_minutes,capital)
    provenance=("claimed_operator_quotes" if now.source==wait.source=="operator"
                else "spot_or_mixed_proxy")
    base={"schema":"btc-v7r6-OTC-decision-mathematics-v1","slot":t.isoformat(),
          "provenance":provenance,"trading_authority":False,
          "both_counterfactual_orders_executed":False,
          "independent_receipt_verification_required":True}
    if not(first and second):
        return {**base,"identified":False,"reason_now":reason_now,
                "reason_wait":reason_wait,"economic_proven":False}
    btc_now=capital/now.ask_usdt_per_btc
    btc_wait=capital/wait.ask_usdt_per_btc
    delta=btc_wait-btc_now
    forecast="WAIT_60" if prediction.expected_wait_advantage_btc>0 else "BUY_NOW"
    observed="WAIT_60" if delta>0 else "BUY_NOW"
    # Positive predicted waits which turned bad count NEGATIVELY, not censored.
    return {**base,"identified":True,"btc_buy_now":btc_now,
            "btc_wait_60":btc_wait,"wait_minus_now_btc":delta,
            "forecast_action":forecast,
            "realized_best_action_conditional_on_full_fills":observed,
            "forecast_action_correct":forecast==observed,
            "incremental_btc_vs_buy_now":delta if forecast=="WAIT_60" else 0.,
            "economic_proven":False}

def markup_robust_direction(spot_at_60,spot_at_120,*,
                             markup_min=OTC_MARKUP_MIN,markup_max=OTC_MARKUP_MAX):
    # This is a FORWARD LABEL, not an input available at publication!
    if not all(isfinite(x) for x in (
        spot_at_60,spot_at_120,markup_min,markup_max)):
        raise ValueError("nonfinite spot")
    if min(spot_at_60,spot_at_120)<=0 or markup_min<0 or markup_max<markup_min:
        raise ValueError("invalid spot/markup")
    if spot_at_120+markup_max<spot_at_60+markup_min:
        return "WAIT_60_ROBUSTLY_CHEAPER"
    if spot_at_60+markup_max<spot_at_120+markup_min:
        return "BUY_NOW_ROBUSTLY_CHEAPER"
    return "NOT_ROBUST_TO_OTC_MARKUP"

def independent_day_economic_evidence(outcomes:Sequence[dict],minimum_days=20):
    if not outcomes:
        return {"calendar_days":0,"resolved":0,"missing":0,
                "conditional_quote_lower95_positive":False,
                "verified_positive_economic_edge":False,"trading_authority":False}
    days={}
    seen=set()
    missing=0
    claimed_operator_only=True
    for event in outcomes:
        slot=event["slot"]
        if slot in seen:
            raise ValueError("duplicated forecast/outcome slot")
        seen.add(slot)
        day=utc(datetime.fromisoformat(slot)).date().isoformat()
        if not event["identified"]:
            missing+=1
            continue
        if event.get("provenance")!="claimed_operator_quotes":
            claimed_operator_only=False
        delta=float(event["incremental_btc_vs_buy_now"])
        if not isfinite(delta):
            raise ValueError("nonfinite OTC difference")
        days.setdefault(day,[]).append(delta)
    blocks=[mean(v) for _,v in sorted(days.items())]
    lower=(mean(blocks)-1.96*stdev(blocks)/sqrt(len(blocks))
           if len(blocks)>1 else None)
    return {"calendar_days":len(blocks),"resolved":sum(len(v) for v in days.values()),
            "missing":missing,
            "mean_daily_incremental_btc_vs_buy_now":mean(blocks) if blocks else None,
            "descriptive_lower95_btc":lower,
            "claimed_operator_quotes_complete":claimed_operator_only and missing==0,
            "conditional_quote_lower95_positive":bool(
                len(blocks)>=minimum_days and missing==0 and
                claimed_operator_only and lower is not None and lower>0),
            # Dict inputs do NOT cryptographically authenticate operator receipts.
            # Even firm dual quotes are not two executed counterfactual orders.
            "verified_positive_economic_edge":False,
            "independent_receipt_verification_required":True,
            "trading_authority":False}
