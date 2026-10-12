"""v7R6 mathematical veto for weak BTC OTC WAIT-60 signals.

Calibration uses past ex-ante published forecasts and fully matured t+60/
t+120 outcomes, one observation from each of the preceding UTC days.
Mathematical research only. No live trading, claims of signed receipts,
engineer/infra changes or confidence guarantees for nonstationary BTC.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import ceil, isfinite
from statistics import mean
from typing import Sequence

UTC=timezone.utc
CAPITAL=147600.0
MIN_PREVIOUS_DAYS=20
ALPHA=.10
MARKUP_LOW=300.0
MARKUP_HIGH=400.0

def aware_utc(t):
    if t.tzinfo is None or t.utcoffset() is None:
        raise ValueError("UTC-aware timestamps required")
    return t.astimezone(UTC)

def worst_case_wait_advantage_btc(spot_now_fill,spot_wait_fill,capital=CAPITAL,
                                  markup_low=MARKUP_LOW,markup_high=MARKUP_HIGH):
    """FORWARD LABEL ONLY: maximal WAIT spread minus minimal NOW spread."""
    values=(spot_now_fill,spot_wait_fill,capital,markup_low,markup_high)
    if any(not isfinite(x) for x in values) or min(spot_now_fill,spot_wait_fill,capital)<=0:
        raise ValueError("nonfinite or nonpositive future price/capital")
    if markup_low<0 or markup_high<markup_low:
        raise ValueError("invalid markup band")
    return capital/(spot_wait_fill+markup_high)-capital/(spot_now_fill+markup_low)

@dataclass(frozen=True)
class MaturedDay:
    issued_utc: datetime
    publicly_issued_utc: datetime
    outcome_matured_utc: datetime
    predicted_nominal_wait_gain_btc: float
    worst_realized_wait_gain_btc: float
    source: str="historical_spot_proxy"

def bound_wait_utility(current_issued_utc: datetime,
                       current_predicted_nominal_wait_gain_btc: float,
                       completed: Sequence[MaturedDay], *,
                       required_days: int=MIN_PREVIOUS_DAYS,
                       alpha: float=ALPHA):
    """Tail-residual mathematical veto without hindsight-chosen success days.

    Predicted WAIT BTC benefit is adjusted by prior-day worst-case OTC
    label errors. An empirical lower quantile is NOT calibrated prospective
    skill in a nonstationary market, and cannot grant trade authority.
    """
    issued=aware_utc(current_issued_utc)
    predicted=float(current_predicted_nominal_wait_gain_btc)
    if not isfinite(predicted):
        raise ValueError("invalid decision-time forecast")
    if required_days<20 or not (0<alpha<.5):
        raise ValueError("precommitted history minimum / tail is invalid")
    expected={issued.date()-timedelta(days=i) for i in range(1,required_days+1)}
    past={}
    for sample in completed:
        t=aware_utc(sample.issued_utc)
        public=aware_utc(sample.publicly_issued_utc)
        matured=aware_utc(sample.outcome_matured_utc)
        if t.date() not in expected:
            continue
        if t.date() in past:
            raise ValueError("duplicate opportunity on same UTC day")
        if (t.hour,t.minute,t.second,t.microsecond)!=(issued.hour,issued.minute,issued.second,issued.microsecond):
            raise ValueError("historical opportunity not on fixed daily UTC issue clock")
        if not t<=public<=t+timedelta(minutes=13):
            raise ValueError("forecast was not published by the frozen 13-minute deadline")
        if matured<t+timedelta(minutes=120) or matured>=issued:
            raise ValueError("outcome unavailable at decision time")
        if sample.source not in ("historical_spot_proxy","claimed_operator_quotes"):
            raise ValueError("unknown quote provenance")
        if not all(isfinite(x) for x in (sample.predicted_nominal_wait_gain_btc,
                                         sample.worst_realized_wait_gain_btc)):
            raise ValueError("nonfinite calibration outcome")
        past[t.date()]=sample
    missing=sorted(expected-set(past))
    basis={"schema":"btc-v7r6-otc-risk-veto-math-v1",
           "decision_utc":issued.isoformat(),
           "required_independent_previous_UTC_days":required_days,
           "calibration_days_available":len(past),
           "missing_precommitted_UTC_days":[d.isoformat() for d in missing],
           "research_only":True,"trading_authority":False,
           "operator_quotes_cryptographically_verified":False,
           "prospective_trade_profit_proven":False}
    if missing:
        return {**basis,"decision":"INSUFFICIENT_MATURED_CALIBRATION",
                "forecast_lower_bound_btc":None,"mathematical_wait_candidate":False}
    residuals=sorted(s.worst_realized_wait_gain_btc-s.predicted_nominal_wait_gain_btc
                     for s in past.values())
    rank=max(1,ceil((len(residuals)+1)*alpha))
    # A 10% percentile can conceal a rare catastrophic historical miss.
    # Check BOTH percentile and bottom-tail expected shortfall. These are
    # descriptive empirical guards, not distribution-free BTC guarantees.
    tail_count=max(1,ceil(alpha*len(residuals)))
    tail_mean=mean(residuals[:tail_count])
    lower=predicted+min(residuals[rank-1],tail_mean)
    return {**basis,
            "decision":"WAIT_CANDIDATE_RESEARCH_ONLY" if lower>0 else "ABSTAIN_WAIT",
            "nominal_wait_gain_forecast_btc":predicted,
            "adverse_residual_lower_quantile_btc":residuals[rank-1],
            "residual_quantile_rank_1based":rank,
            "adverse_tail_average_residual_btc":tail_mean,
            "adverse_tail_days_used":tail_count,
            "forecast_lower_bound_btc":lower,
            "mathematical_wait_candidate":lower>0,
            "tail_alpha":alpha,
            "bound_is_empirical_not_guaranteed":True}
