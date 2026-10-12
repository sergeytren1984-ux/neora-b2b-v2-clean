"""Full numerical replay of SIGNED v7R4 raw source market observations.

The previous independent scorecard verified signed outcome/forecast JSON, but
did not independently re-derive OI and book factor values from raw OKX
responses or contemporary 3m taker pressure from Binance closed 1m rows.

This pure fail-closed replay is safe to run OUTSIDE the time-critical forecast
path. A valid Cosign + Rekor signature of the exact source snapshot MUST be
verified before calling rederive(), and its expected workflow/ref/source SHA
must be checked by the caller. This is source consistency, not model skill.
"""
from __future__ import annotations
import datetime as dt
import json,math
from btc_demand_v7.live_snapshot import (
    strict_closed,spot_state,open_interest_state,liquidity_state,funding_state,
    SOURCE_OI,SOURCE_BOOK,SOURCE_FUNDING
)
from btc_demand_v7.demand_change_v2 import feature,timestamp

CUTOFF_MINUTES=12
MAX_RECEIPT_AGE_SECONDS=120
EXPECTED={
    "oi_okx":(SOURCE_OI,{"ccy":"BTC","period":"5m"}),
    "book_okx":(SOURCE_BOOK,{"instId":"BTC-USDT-SWAP","sz":20}),
    "funding_okx":(SOURCE_FUNDING,{"instId":"BTC-USDT-SWAP"}),
}

def equal_numbers(a,b,label):
    if isinstance(a,bool) or isinstance(b,bool):
        if a is not b:raise ValueError("boolean mismatch at "+label)
    elif a is None or b is None:
        if a is not b:raise ValueError("null mismatch at "+label)
    elif isinstance(a,(float,int)) or isinstance(b,(float,int)):
        x=float(a);y=float(b)
        if (not(math.isfinite(x) and math.isfinite(y))
            or not math.isclose(x,y,rel_tol=1e-11,abs_tol=1e-8)):
            raise ValueError("signed derived market factor differs from raw at "+label)
    elif a!=b:
        raise ValueError("signed market source label mismatch at "+label)

def recursive_equal(actual,expected,path):
    if not isinstance(actual,dict) or not isinstance(expected,dict):
        return equal_numbers(actual,expected,path)
    if set(actual)!=set(expected):
        raise ValueError("signed derived market factor fields changed at "+path)
    for k,v in expected.items():
        recursive_equal(actual[k],v,path+"."+k)

def rederive(snapshot):
    """Rebuild every numeric input of the pressure CUSUM from exact signed raw.

    Invalid or missing optional data must not become observed numeric factors.
    No paid endpoint, no futures historical publication assumptions, no orders.
    """
    if snapshot.get("schema")!="btc-v7-live-shadow-snapshot-v1" or snapshot.get("symbol")!="BTCUSDT":
        raise ValueError("untrusted instrument/source schema")
    if snapshot.get("no_backfill") is not True:
        raise ValueError("backfilled observed source cannot enter prospective contour")
    anchor=timestamp(snapshot["anchor_utc"])
    retrieved=timestamp(snapshot["retrieved_at_utc"])
    if not dt.timedelta(0)<=retrieved-anchor<=dt.timedelta(minutes=CUTOFF_MINUTES):
        raise ValueError("signed market snapshot outside registered publication window")
    anchor_ms=int(anchor.timestamp()*1000)
    receipt_ms=int(retrieved.timestamp()*1000)
    one=strict_closed(snapshot["one_min_rows"],60000,anchor_ms,200)
    five=strict_closed(snapshot["five_min_rows"],300000,anchor_ms,600)
    if len(one)!=len(snapshot["one_min_rows"]) or len(five)!=len(snapshot["five_min_rows"]):
        raise ValueError("post-anchor candle included in signed market source")
    obs=snapshot["observation"]
    fresh=spot_state(one,anchor_ms)
    for k,v in fresh.items():
        equal_numbers(obs.get(k),v,"observation."+k)
    bars=snapshot.get("microflow_rows")
    micro=obs.get("microflow")
    if not isinstance(bars,list) or len(bars)!=6 or not isinstance(micro,dict):
        raise ValueError("unsigned/unregistered 3m contemporary microflow")
    last_close=int(micro["vendor_close_ms"])
    exact=strict_closed(bars,60000,last_close,6)
    if len(exact)!=6 or int(exact[-1][6])+1!=last_close:
        raise ValueError("inconsistent current minute raw")
    request_start=int(micro["request_started_ms"])
    response_end=int(micro["response_received_ms"])
    if (not anchor_ms<=request_start<=response_end<=receipt_ms
        or not 0<=response_end-last_close<=MAX_RECEIPT_AGE_SECONDS*1000):
        raise ValueError("future/old current microflow after observation")
    recent=exact[-3:];prior=exact[:3]
    vol=sum(float(r[5]) for r in recent)
    prevol=sum(float(r[5]) for r in prior)
    if vol<=0 or prevol<=0:raise ValueError("no current trade flow")
    computed={
        "source":"Binance BTCUSDT last six completed 1m taker rows",
        "vendor_close_ms":last_close,
        "request_started_ms":request_start,
        "response_received_ms":response_end,
        "recent3_taker_buy_fraction":sum(float(r[9]) for r in recent)/vol,
        "recent3_volume_vs_prior3":vol/prevol,
        "price_last_closed_1m":float(exact[-1][4])
    }
    recursive_equal(micro,computed,"microflow")
    sources=snapshot.get("raw_optional",{})
    receipts=snapshot.get("optional_receipts",{})
    observed={}
    for name,(url,query) in EXPECTED.items():
        rec=receipts.get(name)
        if not isinstance(rec,dict):
            raise ValueError("unsigned optional HTTP receipt absent: "+name)
        if rec.get("url")!=url or rec.get("query")!=query:
            raise ValueError("unexpected vendor/mismatched market request: "+name)
        start=int(rec["request_started_ms"]);finish=int(rec["response_received_ms"])
        if not(anchor_ms<=start<=finish<=receipt_ms):
            raise ValueError("future/retroactive source HTTP receipt: "+name)
        payload=sources.get(name)
        if payload is None:
            observed[name]=None
            continue
        try:
            if name=="oi_okx":
                computed=open_interest_state(payload,finish)
                if not 0<=finish-int(computed["vendor_observation_ms"])<=15*60*1000:
                    raise ValueError("OI vendor sample outside window")
            elif name=="book_okx":
                computed=liquidity_state(payload)
                if not 0<=finish-int(computed["vendor_timestamp_ms"])<=60000:
                    raise ValueError("stale/top10 book vendor snapshot")
            else:
                computed=funding_state(payload,start,finish)
            observed[name]=computed
        except (ValueError,TypeError,KeyError,IndexError):
            observed[name]=None
    for name,factor in (("oi_okx","oi"),("book_okx","book"),("funding_okx","funding")):
        value=obs.get(factor)
        expected=observed[name]
        if (expected is None)!=(value is None):
            raise ValueError("invented or silently hidden source factor "+factor)
        if value is not None:recursive_equal(value,expected,"observation."+factor)
    _,pressure,readiness=feature(snapshot)
    if (obs.get("calibrated_prediction") is not False
        or obs.get("trading_authority") is not False):
        raise ValueError("raw feature snapshot must not assert trading authority")
    return {
        "schema":"btc-v7r5-independent-source-numerical-replay-v1",
        "anchor_utc":anchor.isoformat(),
        "retrieved_at_utc":retrieved.isoformat(),
        "spot_reference_price":fresh["reference_spot"],
        "contemporary_3m_taker_buy_fraction":computed["recent3_taker_buy_fraction"] if False else micro["recent3_taker_buy_fraction"],
        "oi_available":observed["oi_okx"] is not None,
        "book_available":observed["book_okx"] is not None,
        "funding_available":observed["funding_okx"] is not None,
        "pressure_factor_ready":pressure is not None,
        "source_usable_state":readiness,
        "numerically_recomputed_from_signed_raw":True,
        "trading_authority":False,
        "model_skill_proven":False
    }
