"""Ablation: how early can *historical* signed 1m spot taker data warn?

NOT v7R4, NOT a trading model, NOT a clean untouched prospective replay.
The exact Oct11 outcome was already known before this analysis. Thresholds
are exploratory and selected AFTER the incident was observed; the resulting
metrics MUST NOT be interpreted as out-of-sample predictive skill.

Only uses closed Binance BTCUSDT minute OHLCV+taker, no historical signed
as-of OI/book. Conservative assumed first delivery 2 minutes after candle
close. One alert per UTC day across both directions, never one per side.
All 1m bars are gap/microstructure validated, numerical values finite.
"""
from __future__ import annotations
import argparse,datetime as dt,gzip,hashlib,json,math,pathlib,collections

VOL_ACCEL_THRESHOLD=2.5
BUY_SHARE_UP=.70
BUY_SHARE_DOWN=.30
RECENT_3M_PRICE_VETO_PCT=.30
RECENT_15M_PRICE_VETO_PCT=.30
COMPUTE_TO_DELIVERY_MINUTES=2
LATENCY_PRICE_VETO_PCT=.30
TARGET_MINUTES=60
BAR_PCT=None
LEVELS=(500.,1000.)
UTC=dt.timezone.utc
SOURCE_RUN=38167948896
SOURCE_SHA="f1cead14844d900b23d39d46b5a620bd1a14b2fa"

def instant(ms):
    return dt.datetime.fromtimestamp(ms/1000,UTC).isoformat()

def verify_candles(raw):
    if len(raw)<30000:raise ValueError("minute archive too short")
    previous=None
    for row in raw:
        if len(row)<11:raise ValueError("raw row schema")
        t=int(row[0]);end=int(row[6])+1
        if end!=t+60000 or (previous is not None and t-previous!=60000):
            raise ValueError("gapped/duplicate/unclosed signed minute")
        previous=t
        value=[float(row[k]) for k in (1,2,3,4,5,7,8,9,10)]
        if not all(math.isfinite(x) for x in value):
            raise ValueError("nonfinite signed candle")
        op,hi,lo,cl,vol,quote,trades,buy,buyquote=value
        if not(0<lo<=min(op,cl)<=max(op,cl)<=hi
               and 0<=buy<=vol and 0<=buyquote<=quote
               and trades>=0 and trades.is_integer()):
            raise ValueError("invalid signed minute market mechanics")

def early_pressure(raw,i):
    # Closure i only, no future price or future volume in this detector.
    current=raw[i-2:i+1];older=raw[i-5:i-2]
    vol=sum(float(z[5]) for z in current)
    previous=sum(float(z[5]) for z in older)
    if vol<=0 or previous<=0:return None
    buy=sum(float(z[9]) for z in current)/vol
    ratio=vol/previous
    c=float(raw[i][4])
    short_change=100*(c/float(raw[i-3][4])-1)
    fifteen_change=100*(c/float(raw[i-15][4])-1)
    direction="UP" if buy>=BUY_SHARE_UP else ("DOWN" if buy<=BUY_SHARE_DOWN else None)
    if direction is None or ratio<VOL_ACCEL_THRESHOLD:
        return None
    if (abs(short_change)>=RECENT_3M_PRICE_VETO_PCT
        or abs(fifteen_change)>=RECENT_15M_PRICE_VETO_PCT):
        return None
    return {"direction":direction,
            "taker_buy_fraction_3m":buy,
            "volume_3m_vs_previous_3m":ratio,
            "price_change_3m_pct":short_change,
            "price_change_15m_pct":fifteen_change,
            "source_candle_close_utc":instant(int(raw[i][6])+1)}

def prospective_60m_counterfactual(raw,i,det):
    # Price at the hypothetical *later* public delivery; never use it
    # as a feature. The minute starting AFTER delivery is earliest future.
    delivery=i+COMPUTE_TO_DELIVERY_MINUTES
    if delivery+TARGET_MINUTES>=len(raw):return None
    before=float(raw[i][4]);published_price=float(raw[delivery][4])
    late_move=100*(published_price/before-1)
    threshold_state="MOVED_BEFORE_DELIVERY" if abs(late_move)>=LATENCY_PRICE_VETO_PCT else "EARLY_ELIGIBLE"
    details={}
    for dollar_level in LEVELS:
        lower=published_price-dollar_level;upper=published_price+dollar_level
        winner="NEITHER";touch=None
        for j in range(delivery+1,delivery+TARGET_MINUTES+1):
            high=float(raw[j][2]);low=float(raw[j][3])
            up=high>=upper;down=low<=lower
            if up or down:
                winner="AMBIGUOUS_SAME_MINUTE" if up and down else ("UP" if up else "DOWN")
                # 1m bar OPEN is earliest plausible touch, unlike close.
                touch=instant(int(raw[j][0]))
                break
        eligible=(threshold_state=="EARLY_ELIGIBLE"
                  and winner==det["direction"])
        details[str(int(dollar_level))]={
           "outcome":winner,"first_touch_minute_open_utc":touch,
           "delivered_price":published_price,
           "correct_early_direction":eligible,
           "conservative_lead_minutes":((j-delivery-1) if touch else None),
           "OTC_60min_advance_proven":False}
    return {"hypothetical_delivery_utc":instant(int(raw[delivery][6])+1),
            "price_move_between_compute_and_delivery_pct":late_move,
            "delivery_status":threshold_state,"barriers":details}

def run(gz,out):
    packed=pathlib.Path(gz).read_bytes()
    with gzip.open(gz,"rt") as inp:raw=json.load(inp)
    verify_candles(raw)
    # Continuous minute-level raw input. Candidate universe includes every
    # minute, including unselected times; never count only successful alerts.
    by_day=collections.defaultdict(list)
    incident_start=int(dt.datetime(2026,10,11,15,0,tzinfo=UTC).timestamp()*1000)
    incident_end=int(dt.datetime(2026,10,11,17,0,tzinfo=UTC).timestamp()*1000)
    preceding=[]
    for i in range(20,len(raw)-TARGET_MINUTES-COMPUTE_TO_DELIVERY_MINUTES):
        day=instant(int(raw[i][6])+1)[:10]
        det=early_pressure(raw,i)
        if det is None:continue
        resolved=prospective_60m_counterfactual(raw,i,det)
        if resolved is None:continue
        candidate={**det,**resolved}
        by_day[day].append(candidate)
        ct=int(raw[i][6])+1
        if incident_start<=ct<=incident_end:
            preceding.append(candidate)
    first_budgeted={k:v[0] for k,v in sorted(by_day.items()) if v}
    test_days=sorted(x for x in first_budgeted if x>="2026-10-05" and x<="2026-10-11")
    outcomes={}
    for category,days in (
        ("entire_known_hist",sorted(first_budgeted)),
        ("already_examined_oct5_11",test_days),
    ):
        samples=[first_budgeted[d] for d in days]
        stats={"days_with_one_alert":len(samples),
               "available_calendar_days":len(set(instant(int(r[6])+1)[:10] for r in raw
                          if ("2026-10-05"<=instant(int(r[6])+1)[:10]<="2026-10-11")
                             or category=="entire_known_hist")),
               "no_alert_days_not_silently_excluded":True}
        for level in LEVELS:
            key=str(int(level))
            eligible=[x for x in samples if x["delivery_status"]=="EARLY_ELIGIBLE"]
            success=[x for x in eligible if x["barriers"][key]["correct_early_direction"]]
            stats["dollars_"+key]={
               "alerts_published":len(samples),
               "eligible_pre_move_alerts":len(eligible),
               "correct_direction_within60m":len(success),
               "fraction_correct_of_all_published":len(success)/len(samples) if samples else None,
               "n_with_lead_at_least10m":sum(x["barriers"][key]["conservative_lead_minutes"] is not None
                   and x["barriers"][key]["conservative_lead_minutes"]>=10 for x in success),
               "n_with_lead_at_least30m":sum(x["barriers"][key]["conservative_lead_minutes"] is not None
                   and x["barriers"][key]["conservative_lead_minutes"]>=30 for x in success),
               "n_with_lead_at_least60m":sum(x["barriers"][key]["conservative_lead_minutes"] is not None
                   and x["barriers"][key]["conservative_lead_minutes"]>=60 for x in success),
               "real_OTC_operator_fill_data":False}
        outcomes[category]=stats
    target=next((x for x in preceding
                  if x["source_candle_close_utc"]=="2026-10-11T15:34:00+00:00"),None)
    incident_day=first_budgeted.get("2026-10-11")
    report={"schema":"btc-v7r5-signed-minute-flow-incident-ablation-v1",
            "signed_archive_run":SOURCE_RUN,
            "signed_archive_producer_sha":SOURCE_SHA,
            "signed_gzip_sha256":hashlib.sha256(packed).hexdigest(),
            "raw_minute_rows":len(raw),
            "first_minute_utc":instant(int(raw[0][0])),
            "last_closed_minute_utc":instant(int(raw[-1][6])+1),
            "spot_only_no_OI_or_book":True,
            "thresholds_chosen_after_incident_known":True,
            "historical_signatures_must_be_verified_before_execution":True,
            "published_2min_after_close_IS_ASSUMPTION_not_logged_fact":True,
            "same_UTC_day_directional_alert_budget":1,
            "fixed_exploratory_conditions":{
              "buy_frac_up":BUY_SHARE_UP,"buy_frac_down":BUY_SHARE_DOWN,
              "3m_volume_acceleration":VOL_ACCEL_THRESHOLD,
              "3m_price_veto_abs_pct":RECENT_3M_PRICE_VETO_PCT,
              "15m_price_veto_abs_pct":RECENT_15M_PRICE_VETO_PCT,
              "compute_to_delivery_minutes":COMPUTE_TO_DELIVERY_MINUTES,
              "dollars_barriers":LEVELS},
            "evaluations":outcomes,
            "oct11_first_eligible_candidate":incident_day,
            "oct11_1534_utc_candidate":target,
            "oct11_15to17_all_candidates":preceding,
            "oct11_15to17_candidates_count":len(preceding),
            "false_alerts_included":True,
            "future_prospective_skill_proven":False,
            "trading_authority":False}
    dest=pathlib.Path(out);dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_text(json.dumps(report,sort_keys=True,ensure_ascii=False,indent=2,allow_nan=False)+"\n")
    summary={"oct11_first_budgeted_time":incident_day.get("source_candle_close_utc") if incident_day else None,
             "oct11_1534_candidate_detected":bool(target),
             "oct11_1534_candidate":target,
             "known_test":outcomes["already_examined_oct5_11"]}
    print("BTC_V7R5_ONE_MINUTE_EARLY_FLOW_COUNTERFACTUAL",json.dumps(summary,sort_keys=True))

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--signed-minutes",required=True)
    p.add_argument("--out",required=True)
    a=p.parse_args()
    run(a.signed_minutes,a.out)
if __name__=="__main__":main()
