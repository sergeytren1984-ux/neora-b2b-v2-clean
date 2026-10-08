"""Frozen numerical production emitter core for vNext5R4.

No training exists here.  Forecasts are deterministically recomputed from closed
Binance BTCUSDT candles and exact immutable vNext5 model binaries. Outcomes are
deterministically recomputed from forward candles after the forecast anchor.
The same functions are used by production emission and independent replay.
"""
from __future__ import annotations

import hashlib
import json
import math
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import joblib
import numpy as np

from predictive_vnext4r6.live_features import (
    EARLY15M_NAMES, HOURLY_NAMES, early15m_feature, hourly_feature,
)
from predictive_vnext5.predictor import (
    classifier_raw_probability, hazard_raw_probability,
)

UTC=timezone.utc
SYMBOL="BTCUSDT"
SOURCE="Binance data-api closed klines"
SOURCE_ENDPOINT="https://data-api.binance.vision/api/v3/klines"
MODEL_FILES={
    "1h":(
        "head_1h_classifier.joblib",
        "9c24cb79f59a6a0b09e0f2980521e071c02cf749e4d14f88713b096fa569ed83",
    ),
    "4h":(
        "head_4h_classifier.joblib",
        "1076407df238eb827ba36b7d69075802940dc84d1954f89943d76db93e542535",
    ),
    "24h_classifier":(
        "head_24h_classifier.joblib",
        "1d024c9df3386b4a27ecd0aedb95eacf2fa6bf083ff119ace93dd5303f96c1ac",
    ),
    "24h_competing_risks":(
        "head_24h_competing_risks.joblib",
        "a842001ff27500457dc2cece889c63111a6430fa29cf22633b9d7d5626539f0d",
    ),
}
HEADS={
    "1h":{
        "interval":"15m","duration_ms":900000,"min_history":385,
        "horizon_steps":4,"horizon":timedelta(hours=1),
        "candidates":["1h"],"base_names":EARLY15M_NAMES,
    },
    "4h":{
        "interval":"15m","duration_ms":900000,"min_history":385,
        "horizon_steps":16,"horizon":timedelta(hours=4),
        "candidates":["4h"],"base_names":EARLY15M_NAMES,
    },
    "24h":{
        "interval":"1h","duration_ms":3600000,"min_history":170,
        "horizon_steps":24,"horizon":timedelta(hours=24),
        "candidates":["24h_classifier","24h_competing_risks"],
        "base_names":HOURLY_NAMES,
    },
}


def canonical(obj):
    return (
        json.dumps(
            obj,sort_keys=True,separators=(",",":"),
            ensure_ascii=False,allow_nan=False,
        )+"\n"
    ).encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def parse_utc(value):
    dt=datetime.fromisoformat(str(value).replace("Z","+00:00"))
    if dt.tzinfo is None:
        raise ValueError("timestamp must be timezone aware")
    return dt.astimezone(UTC)


def _locate(root:Path,name:str)->Path:
    hits=list(Path(root).rglob(name))
    if len(hits)!=1:
        raise ValueError(f"expected exactly one {name}, got {hits}")
    return hits[0]


def _sha(path:Path)->str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_model_authority(model_root:Path):
    model_root=Path(model_root).resolve()
    out={}
    for candidate,(name,want) in MODEL_FILES.items():
        path=_locate(model_root,name)
        if _sha(path)!=want:
            raise ValueError("model artifact SHA mismatch: "+candidate)
        bundle=joblib.load(path)
        if not isinstance(bundle,dict):
            raise ValueError("invalid model bundle: "+candidate)
        if bundle.get("trading_authority") is not False:
            raise ValueError("model bundle trading authority drift")
        expected_head="24h" if candidate.startswith("24h") else candidate
        if bundle.get("head")!=expected_head:
            raise ValueError("model bundle head mismatch: "+candidate)
        if int(bundle.get("base_feature_count",-1))!=len(HEADS[expected_head]["base_names"]):
            raise ValueError("model base feature count mismatch: "+candidate)
        names=bundle.get("feature_names")
        expected_names=HEADS[expected_head]["base_names"]
        if not isinstance(names,list) or names[:len(expected_names)]!=expected_names:
            raise ValueError("model feature names mismatch: "+candidate)
        out[candidate]=bundle
    return out


def _validate_row(row,duration_ms):
    if not isinstance(row,list) or len(row)<10:
        raise ValueError("invalid kline shape")
    if int(row[6])!=int(row[0])+duration_ms-1:
        raise ValueError("invalid kline close timestamp")
    o,h,l,c,v=map(float,(row[1],row[2],row[3],row[4],row[5]))
    trades=int(row[8]); taker=float(row[9])
    if not all(math.isfinite(x) for x in (o,h,l,c,v,taker)):
        raise ValueError("non-finite market data")
    if min(o,h,l,c)<=0 or l>min(o,c) or h<max(o,c) or h<l:
        raise ValueError("invalid OHLC invariant")
    if v<0 or taker<0 or taker>v or trades<0:
        raise ValueError("invalid activity invariant")


def validate_forecast_klines(head,anchor,rows):
    cfg=HEADS[head]
    anchor=parse_utc(anchor) if not isinstance(anchor,datetime) else anchor.astimezone(UTC)
    if not isinstance(rows,list) or len(rows)<cfg["min_history"]:
        raise ValueError("insufficient closed candle history")
    for row in rows:
        _validate_row(row,cfg["duration_ms"])
    if any(
        int(b[0])-int(a[0])!=cfg["duration_ms"]
        for a,b in zip(rows,rows[1:])
    ):
        raise ValueError("forecast candle gap or duplicate")
    end_ms=int(anchor.timestamp()*1000)
    if int(rows[-1][6])+1!=end_ms:
        raise ValueError("latest closed candle does not end at anchor")
    if int(rows[-1][0])>=end_ms:
        raise ValueError("forecast includes candle opened at/after anchor")
    return rows


def validate_outcome_klines(head,anchor,due,rows):
    cfg=HEADS[head]
    anchor=parse_utc(anchor) if not isinstance(anchor,datetime) else anchor.astimezone(UTC)
    due=parse_utc(due) if not isinstance(due,datetime) else due.astimezone(UTC)
    expected=int((due-anchor).total_seconds()*1000/cfg["duration_ms"])
    if not isinstance(rows,list) or len(rows)!=expected:
        raise ValueError("outcome candle count mismatch")
    for row in rows:
        _validate_row(row,cfg["duration_ms"])
    if int(rows[0][0])!=int(anchor.timestamp()*1000):
        raise ValueError("outcome first candle does not open at anchor")
    if int(rows[-1][6])+1!=int(due.timestamp()*1000):
        raise ValueError("outcome last candle does not close at due")
    if any(
        int(b[0])-int(a[0])!=cfg["duration_ms"]
        for a,b in zip(rows,rows[1:])
    ):
        raise ValueError("outcome candle gap or duplicate")
    return rows


def _arrays(rows):
    return tuple(
        np.asarray([float(row[j]) for row in rows],dtype=float)
        for j in (2,3,4,5,8,9)
    )


def _feature_document(head,rows):
    hi,lo,c,v,trades,taker=_arrays(rows)
    if head in ("1h","4h"):
        x,meta=early15m_feature(hi,lo,c,v,trades,taker)
        vol=float(meta["rv4h"])
    else:
        x,meta=hourly_feature(hi,lo,c,v,trades,taker)
        vol=float(meta["rv24"])
    if not np.all(np.isfinite(x)) or not math.isfinite(vol) or vol<=0:
        raise ValueError("invalid computed feature/volatility")
    doc={
        "schema":"btc-predictive-vnext5r4-feature-vector-v1",
        "head":head,
        "feature_names":HEADS[head]["base_names"],
        "values":[float(z) for z in x],
        "reference_price":float(meta["reference_price"]),
        "volatility":vol,
    }
    return doc


def recompute_forecast_from_raw(head,raw_doc,model_root):
    if head not in HEADS:
        raise ValueError("invalid head")
    if type(raw_doc) is not dict:
        raise ValueError("forecast raw must be an object")
    allowed={
        "schema","source","source_endpoint","symbol","interval",
        "anchor_utc","retrieved_at_utc","klines","feature_document",
        "feature_sha256",
    }
    if set(raw_doc)!=allowed:
        raise ValueError("forecast raw schema mismatch")
    if raw_doc["schema"]!="btc-predictive-vnext5r4-market-forecast-raw-v1":
        raise ValueError("forecast raw schema id mismatch")
    cfg=HEADS[head]
    if (
        raw_doc["source"]!=SOURCE
        or raw_doc["source_endpoint"]!=SOURCE_ENDPOINT
        or raw_doc["symbol"]!=SYMBOL
        or raw_doc["interval"]!=cfg["interval"]
    ):
        raise ValueError("forecast raw source contract mismatch")
    anchor=parse_utc(raw_doc["anchor_utc"])
    rows=validate_forecast_klines(head,anchor,raw_doc["klines"])
    feature=_feature_document(head,rows)
    if raw_doc["feature_document"]!=feature:
        raise ValueError("signed feature document differs from recomputation")
    feature_hash=digest(canonical(feature))
    if raw_doc["feature_sha256"]!=feature_hash:
        raise ValueError("signed feature hash differs from recomputation")

    models=load_model_authority(Path(model_root))
    base=feature["values"]
    if head in ("1h","4h"):
        probabilities={
            head:[
                float(x) for x in classifier_raw_probability(
                    models[head],base,1.0,1.0
                )
            ]
        }
    else:
        probabilities={
            "24h_classifier":[
                float(x) for x in classifier_raw_probability(
                    models["24h_classifier"],base,1.0,1.0
                )
            ],
            "24h_competing_risks":[
                float(x) for x in hazard_raw_probability(
                    models["24h_competing_risks"],base,1.0,1.0
                )
            ],
        }
    unit=(
        feature["reference_price"]
        * feature["volatility"]
        * math.sqrt(float(cfg["horizon_steps"]))
    )
    return {
        "head":head,
        "anchor_utc":anchor.isoformat(),
        "due_utc":(anchor+cfg["horizon"]).isoformat(),
        "query_type":"CANONICAL",
        "target_id":"CANONICAL_SIGMA_1_1_V1",
        "lower_sigma":1.0,
        "upper_sigma":1.0,
        "predictions":probabilities,
        "artifact_sha256":{
            c:MODEL_FILES[c][1] for c in cfg["candidates"]
        },
        "volatility":feature["volatility"],
        "reference_price":feature["reference_price"],
        "lower_price":float(feature["reference_price"]-unit),
        "upper_price":float(feature["reference_price"]+unit),
        "feature_sha256":feature_hash,
    }


def classify_first_passage(rows,lower,upper):
    lower=float(lower); upper=float(upper)
    if not (math.isfinite(lower) and math.isfinite(upper) and lower<upper):
        raise ValueError("invalid frozen barriers")
    for row in rows:
        down=float(row[3])<=lower
        up=float(row[2])>=upper
        close=datetime.fromtimestamp((int(row[6])+1)/1000,UTC).isoformat()
        if down and up:
            return "AMBIGUOUS_SAME_BAR",close
        if down:
            return "LOWER_FIRST",close
        if up:
            return "UPPER_FIRST",close
    return "NEITHER",None


def recompute_outcome_from_raw(head,raw_doc,lower_price,upper_price):
    if type(raw_doc) is not dict:
        raise ValueError("outcome raw must be an object")
    allowed={
        "schema","source","source_endpoint","symbol","interval",
        "anchor_utc","due_utc","retrieved_at_utc","klines",
    }
    if set(raw_doc)!=allowed:
        raise ValueError("outcome raw schema mismatch")
    if raw_doc["schema"]!="btc-predictive-vnext5r4-market-outcome-raw-v1":
        raise ValueError("outcome raw schema id mismatch")
    cfg=HEADS[head]
    if (
        raw_doc["source"]!=SOURCE
        or raw_doc["source_endpoint"]!=SOURCE_ENDPOINT
        or raw_doc["symbol"]!=SYMBOL
        or raw_doc["interval"]!=cfg["interval"]
    ):
        raise ValueError("outcome raw source contract mismatch")
    anchor=parse_utc(raw_doc["anchor_utc"])
    due=parse_utc(raw_doc["due_utc"])
    rows=validate_outcome_klines(head,anchor,due,raw_doc["klines"])
    cls,touch=classify_first_passage(rows,lower_price,upper_price)
    return {
        "head":head,
        "anchor_utc":anchor.isoformat(),
        "due_utc":due.isoformat(),
        "query_type":"CANONICAL",
        "target_id":"CANONICAL_SIGMA_1_1_V1",
        "lower_sigma":1.0,
        "upper_sigma":1.0,
        "outcome_class":cls,
        "first_touch_time_utc":touch,
        "lower_price":float(lower_price),
        "upper_price":float(upper_price),
    }


def _request_klines(params):
    query=urllib.parse.urlencode(params)
    req=urllib.request.Request(
        SOURCE_ENDPOINT+"?"+query,
        headers={"User-Agent":"btc-predictive-vnext5r4"},
    )
    with urllib.request.urlopen(req,timeout=30) as response:
        if response.status!=200:
            raise RuntimeError("Binance HTTP status not 200")
        rows=json.loads(response.read())
    if not isinstance(rows,list):
        raise RuntimeError("Binance kline response is not list")
    return rows


def fetch_forecast_raw(head,anchor,model_root):
    cfg=HEADS[head]
    anchor=parse_utc(anchor) if not isinstance(anchor,datetime) else anchor.astimezone(UTC)
    rows=_request_klines({
        "symbol":SYMBOL,
        "interval":cfg["interval"],
        "endTime":int(anchor.timestamp()*1000)-1,
        "limit":1000,
    })
    closed=[r for r in rows if int(r[6])+1<=int(anchor.timestamp()*1000)]
    validate_forecast_klines(head,anchor,closed)
    feature=_feature_document(head,closed)
    raw={
        "schema":"btc-predictive-vnext5r4-market-forecast-raw-v1",
        "source":SOURCE,
        "source_endpoint":SOURCE_ENDPOINT,
        "symbol":SYMBOL,
        "interval":cfg["interval"],
        "anchor_utc":anchor.isoformat(),
        "retrieved_at_utc":datetime.now(UTC).isoformat(),
        "klines":closed,
        "feature_document":feature,
        "feature_sha256":digest(canonical(feature)),
    }
    forecast=recompute_forecast_from_raw(head,raw,model_root)
    return raw,forecast


def fetch_outcome_raw(head,anchor,due):
    cfg=HEADS[head]
    anchor=parse_utc(anchor) if not isinstance(anchor,datetime) else anchor.astimezone(UTC)
    due=parse_utc(due) if not isinstance(due,datetime) else due.astimezone(UTC)
    rows=_request_klines({
        "symbol":SYMBOL,
        "interval":cfg["interval"],
        "startTime":int(anchor.timestamp()*1000),
        "endTime":int(due.timestamp()*1000)-1,
        "limit":1000,
    })
    validate_outcome_klines(head,anchor,due,rows)
    return {
        "schema":"btc-predictive-vnext5r4-market-outcome-raw-v1",
        "source":SOURCE,
        "source_endpoint":SOURCE_ENDPOINT,
        "symbol":SYMBOL,
        "interval":cfg["interval"],
        "anchor_utc":anchor.isoformat(),
        "due_utc":due.isoformat(),
        "retrieved_at_utc":datetime.now(UTC).isoformat(),
        "klines":rows,
    }


def nearest_closed_anchor(head,now=None):
    """Frozen primary UTC phase: hourly, four-hourly, daily 00 UTC."""
    now=(now or datetime.now(UTC)).astimezone(UTC)
    base=now.replace(minute=0,second=0,microsecond=0)
    if head=="1h":
        return base
    if head=="4h":
        return base.replace(hour=(base.hour//4)*4)
    if head=="24h":
        return base.replace(hour=0)
    raise ValueError("invalid head")


def historical_replay_anchor(head,now=None):
    """Completed real-market anchor for non-prospective engineering replay."""
    now=(now or datetime.now(UTC)).astimezone(UTC)
    cfg=HEADS[head]
    safe=now-cfg["horizon"]-timedelta(hours=2)
    return nearest_closed_anchor(head,safe)
