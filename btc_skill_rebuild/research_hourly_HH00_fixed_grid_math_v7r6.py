"""Pure mathematical HH:00 prospective score grid for frozen v7R6 research.

Research-only: no data collection, GitHub writes, signatures, workflows,
retuning or trade recommendations. Original GitHub commits/source receipts
must be independently checked by the caller: this module only checks the
mathematical chronology and identical fixed due denominator.

The earlier research_prospective_fixed_grid_v7r6.py counts 15-minute slots.
That is NOT the subsequently specified HH:00 publication schedule and must
never be silently used as its missing-forecast denominator.
"""
from __future__ import annotations
import datetime as dt, math, statistics

UTC=dt.timezone.utc
START=dt.datetime(2026,10,13,tzinfo=UTC)
END=dt.datetime(2026,10,20,tzinfo=UTC)
CODE_SHA1="9709e5c8b886f4f362fd003d0af91f74e3e9dc38"
WEIGHTS_SHA256="cddf85d3e8b352b1eae4560ff145e927b9c7f0da5853d48d725e535f0f6f772f"
HORIZONS={"1h":(1,.007),"4h":(4,.012),"24h":(24,.02)}
PRIOR={
    "1h":(.03281423804226919,.027067111605487578,.9401186503522432),
    "4h":(.05128205128205128,.03678929765886288,.9119286510590858),
    "24h":(.14126744624669935,.06808751414560543,.7906450396076952)}
CLASSES=("UP","DOWN","RANGE")

def utc(value):
    if isinstance(value,str):value=dt.datetime.fromisoformat(value.replace("Z","+00:00"))
    if not isinstance(value,dt.datetime) or value.tzinfo is None:
        raise ValueError("UTC offset required")
    return value.astimezone(UTC)

def score(p,y):
    if len(p)!=3 or y not in CLASSES or any(not math.isfinite(float(x)) or not 0<=float(x)<=1 for x in p):
        raise ValueError("invalid three-way probabilities")
    if abs(sum(map(float,p))-1)>1e-9:raise ValueError("probabilities do not sum to one")
    return sum((float(p[i])-int(CLASSES[i]==y))**2 for i in range(3))/3

def hourly_slots(asof):
    asof=utc(asof)
    stop=min(asof,END-dt.timedelta(hours=1))
    if stop<START:return []
    return [START+dt.timedelta(hours=i) for i in range(int((stop-START).total_seconds()//3600)+1)]

def valid_forecast(slot,record):
    if not START<=slot<END or slot.minute or slot.second or slot.microsecond:
        raise ValueError("forecast is not in original HH:00 grid")
    pub=utc(record["public_commit_utc"])
    src=utc(record["source_commit_utc"])
    retrieved=utc(record["source_retrieved_utc"])
    anchor=utc(record["source_anchor_utc"])
    if not(anchor==slot and retrieved<=src<=pub and slot<=pub<=slot+dt.timedelta(minutes=13)):
        raise ValueError("forecast not issued from already-public R5 source before HH:13")
    if record.get("source_path")!=(
        "btc_v7r3_evidence/slots/"+slot.strftime("%Y%m%dT%H00Z")+"/snapshot.json"):
        raise ValueError("wrong R5 as-of source slot")
    if not record.get("source_blob_sha1") or len(record["source_blob_sha1"])!=40:
        raise ValueError("missing original source Git blob identity")
    if record.get("forecast_code_blob_sha1")!=CODE_SHA1 or record.get("weights_sha256")!=WEIGHTS_SHA256:
        raise ValueError("forecast code or weights not frozen")
    if not record.get("forecast_commit_sha") or len(record["forecast_commit_sha"])!=40:
        raise ValueError("missing original Git publication identity")
    if record.get("trading_authority") is not False:
        raise ValueError("research-only source cannot authorize trades")
    heads=record["heads"]
    if set(heads)!=set(HORIZONS):raise ValueError("three horizon heads required")
    ref=None
    for h,(hours,threshold) in HORIZONS.items():
        v=heads[h]
        if utc(v["target_utc"])!=slot+dt.timedelta(hours=hours) or float(v["threshold"])!=threshold:
            raise ValueError("target/threshold retuned after publication")
        price=float(v["reference_price"])
        if not math.isfinite(price) or price<=0 or ref is not None and price!=ref:
            raise ValueError("invalid common reference spot")
        ref=price
        score(v["p"],"RANGE")
    return True

def valid_outcome(slot,h,forecast,obs,asof):
    hours,_=HORIZONS[h]
    target=slot+dt.timedelta(hours=hours)
    if target>asof:return None
    if not obs:return None
    # Outcome may be published later but its target bar must be the exact
    # closed five-minute endpoint, never the nearest available candle.
    if utc(obs["closed_bar_end_utc"])!=target:
        raise ValueError("nearest future price substituted for exact target")
    pub=utc(obs["outcome_snapshot_commit_utc"])
    retrieved=utc(obs["outcome_snapshot_retrieved_utc"])
    if not target<=retrieved<=pub<=asof:
        raise ValueError("outcome not yet public at score time")
    if not obs.get("outcome_snapshot_blob_sha1"):
        raise ValueError("unidentified future source")
    px=float(obs["close"])
    if not math.isfinite(px) or px<=0:raise ValueError("invalid actual future spot")
    head=forecast["heads"][h]
    movement=px/float(head["reference_price"])-1
    threshold=HORIZONS[h][1]
    y="UP" if movement>threshold else "DOWN" if movement< -threshold else "RANGE"
    model=score(head["p"],y)
    prior=score(PRIOR[h],y)
    return {"class":y,"gain":prior-model,"model_brier":model,
            "prior_brier":prior,"return_fraction":movement}

def audit(asof,forecasts,outcomes):
    asof=utc(asof)
    grid=hourly_slots(asof)
    keys={x.isoformat() for x in grid}
    off_grid=sum(key not in keys for key in forecasts)
    out={"schema":"btc-v7r6-research-hourly-HH00-fixed-grid-math-v1",
         "asof_utc":asof.isoformat(),
         "hourly_due":len(grid),"published_on_time":0,
         "missing_forecast":0,"off_grid_forecasts_excluded":off_grid,
         "all_missing_slots_retained":True,
         "R5_signature_independently_verified":False,
         "research_forecast_signature_independently_verified":False,
         "trading_authority":False,"horizons":{}}
    accepted={}
    for slot in grid:
        key=slot.isoformat()
        f=forecasts.get(key)
        if f is None:
            out["missing_forecast"]+=1
            continue
        valid_forecast(slot,f)
        accepted[key]=f
        out["published_on_time"]+=1
    for h,(hours,_) in HORIZONS.items():
        matured=[slot for slot in grid if slot+dt.timedelta(hours=hours)<=asof]
        nonoverlap=[slot for slot in matured if (slot-START).total_seconds()%(hours*3600)==0]
        resolved=[];resolved_nonoverlap=[];unresolved=0
        for slot in matured:
            key=slot.isoformat()
            f=accepted.get(key)
            if f is None:continue
            result=valid_outcome(slot,h,f,outcomes.get((key,h)),asof)
            if result is None:
                unresolved+=1;continue
            resolved.append((slot,result))
            if slot in nonoverlap:resolved_nonoverlap.append((slot,result))
        days={s.date() for s,_ in resolved_nonoverlap}
        gains=[v["gain"] for _,v in resolved]
        ngains=[v["gain"] for _,v in resolved_nonoverlap]
        out["horizons"][h]={
            "matured_HH00_due":len(matured),
            "matured_forecasts_missing":sum(s.isoformat() not in accepted for s in matured),
            "matured_on_time_forecast_without_exact_outcome":unresolved,
            "matured_scored":len(resolved),
            "nonoverlap_HH00_due":len(nonoverlap),
            "nonoverlap_scored":len(resolved_nonoverlap),
            "nonoverlap_missing_or_unresolved":len(nonoverlap)-len(resolved_nonoverlap),
            "UTC_days_with_nonoverlap_scores":len(days),
            "independent_directional_first_touch_events":None,
            "directional_endpoint_labels_not_first_touch_events":
                sum(v["class"]!="RANGE" for _,v in resolved),
            "mean_Brier_gain_vs_pre_epoch_prior_overlapping":
                statistics.mean(gains) if gains else None,
            "mean_Brier_gain_vs_pre_epoch_prior_nonoverlap":
                statistics.mean(ngains) if ngains else None,
            "20_independent_days_met":len(days)>=20,
            "statistical_lower_bound_proven_positive":False}
    return out
