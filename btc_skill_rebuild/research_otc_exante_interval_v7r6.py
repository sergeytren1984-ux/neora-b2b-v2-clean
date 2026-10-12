"""v7R6 single-head mathematical OTC interval decision.

INPUT: price intervals for operator execution around t+60 and t+120,
computed and published BEFORE either future execution. Any uncalibrated
or untimely input => NO_FORECAST. Neither future price nor future OHLC
is a feature here. Research math, not live release and not trading advice.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime,timedelta,timezone
from math import isfinite
from typing import Optional

UTC=timezone.utc
MAX_LATENCY_MIN=13
MIN_PROSPECTIVE_CALIBRATED_DAYS=20

@dataclass(frozen=True)
class PriceInterval:
    low: float
    high: float

@dataclass(frozen=True)
class TimelyPair:
    issue_utc: datetime
    publication_utc: datetime
    for_now_execution_at_60m: PriceInterval
    for_wait_execution_at_120m: PriceInterval
    calibrated_completed_independent_days: int
    input_received_before_issue: bool
    prospective_receipts_authenticated: bool
    input_source_sha256: Optional[str]=None
    last_completed_calibration_utc: Optional[datetime]=None
    retrospective_joint_interval_coverage: Optional[float]=None
    missing_predeclared_calibration_days: int=0

def _checked_time(t):
    if not isinstance(t,datetime) or t.tzinfo is None or t.utcoffset() is None:
        raise ValueError('timezone-aware public forecast required')
    return t.astimezone(UTC)

def _checked_interval(p):
    if not all(isfinite(v) and v>0 for v in (p.low,p.high)) or p.low>p.high:
        raise ValueError('invalid future price uncertainty interval')

def otc_interval_decision(forecast:TimelyPair, *,
                          available_usdt:float=147600.,
                          markup_min:float=300.,markup_max:float=400.):
    issue=_checked_time(forecast.issue_utc)
    public=_checked_time(forecast.publication_utc)
    _checked_interval(forecast.for_now_execution_at_60m)
    _checked_interval(forecast.for_wait_execution_at_120m)
    if not all(isfinite(z) for z in (available_usdt,markup_min,markup_max)):
        raise ValueError('nonfinite money or markup')
    if available_usdt<=0 or markup_min<0 or markup_max<markup_min:
        raise ValueError('invalid capital or possible operator markup')
    if not forecast.input_received_before_issue or public<issue or public>issue+timedelta(minutes=MAX_LATENCY_MIN):
        return {'mathematical_verdict':'NO_TIMELY_VALID_FORECAST','trading_authority':False,
                'reason':'late_or_unavailable_asof_inputs'}
    if (forecast.calibrated_completed_independent_days<MIN_PROSPECTIVE_CALIBRATED_DAYS
            or forecast.missing_predeclared_calibration_days!=0
            or forecast.last_completed_calibration_utc is None):
        return {'mathematical_verdict':'INSUFFICIENT_CALIBRATION','trading_authority':False,
                'reason':'missing_or_incomplete_matured_daily_coverage'}
    if _checked_time(forecast.last_completed_calibration_utc)>=issue:
        return {'mathematical_verdict':'UNMATURED_CALIBRATION','trading_authority':False,
                'reason':'calibration_not_available_before_issue'}
    coverage=forecast.retrospective_joint_interval_coverage
    if coverage is None or not isfinite(coverage) or not 0<=coverage<=1 or coverage<0.90:
        return {'mathematical_verdict':'UNCALIBRATED_PRICE_INTERVALS','trading_authority':False,
                'reason':'prior_matured_joint_coverage_below_90pct_or_missing'}
    if not forecast.prospective_receipts_authenticated:
        return {'mathematical_verdict':'UNVERIFIED_MATH_INPUTS','trading_authority':False,
                'reason':'no_independent_prospective_receipt_verification'}
    if forecast.input_source_sha256 is None or len(forecast.input_source_sha256)!=64 or any(c not in '0123456789abcdef' for c in forecast.input_source_sha256):
        return {'mathematical_verdict':'UNVERIFIED_MATH_INPUTS','trading_authority':False,
                'reason':'unverifiable_input_hash'}
    now=forecast.for_now_execution_at_60m
    wait=forecast.for_wait_execution_at_120m
    lower=available_usdt/(wait.high+markup_max)-available_usdt/(now.low+markup_min)
    upper=available_usdt/(wait.low+markup_min)-available_usdt/(now.high+markup_max)
    if lower>upper+1e-12:raise ValueError('invalid economic interval')
    verdict=('WAIT_RESEARCH_CANDIDATE' if lower>0 else
             'NOW_RESEARCH_CANDIDATE' if upper<0 else
             'UNRESOLVED_NO_TRADE_SIGNAL')
    return {'mathematical_verdict':verdict,
            'wait_minus_now_BTC_lower':lower,
            'wait_minus_now_BTC_upper':upper,
            'funding_and_operator_fill_risks_NOT_modeled':True,
            'future_execution_price_interval_coverage_NOT_internally_verified':True,
            'trading_authority':False,
            'this_does_not_prove_trade_profit':True}
