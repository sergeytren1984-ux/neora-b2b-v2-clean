from __future__ import annotations
import hashlib, json, math, sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"runtime"))
from frozen_inference import calibrated_candidate_probabilities, frozen_artifact

FEATURES=[
"returns_pct.1h",
"features.trailing_return_3h_pct",
"features.trailing_return_6h_pct",
"features.trailing_return_24h_pct",
"features.trailing_return_72h_pct",
"features.spot_vs_ema20_pct",
"features.ema20_vs_ema50_pct",
"features.rsi14_sma",
"features.realized_volatility_24h_log_pct",
"features.candle_range_1h_pct",
"features.close_location_1h",
"features.distance_to_24h_high_pct",
"features.distance_to_24h_low_pct",
"features.log_volume_z24",
"features.log_trades_z24",
"microstructure.taker_imbalance_1h",
"microstructure.cvd_4h_ratio",
"microstructure.cvd_24h_ratio",
"microstructure.taker_imbalance_accel_1h_24h",
]

def _f(c,k): return float(c[k])

def _ema(vals,span):
    a=2.0/(span+1.0)
    x=float(vals[0])
    for v in vals[1:]: x=a*float(v)+(1.0-a)*x
    return x

def _ret(c,n): return 100.0*(c[-1]/c[-1-n]-1.0)

def _imb(candles,w):
    a=candles[-w:]
    den=sum(_f(x,"volume") for x in a)
    if den<=0: raise ValueError("nonpositive volume")
    return sum(2.0*_f(x,"taker_buy_base")-_f(x,"volume") for x in a)/den

def _zlog(candles,key):
    a=[math.log1p(max(0.0,_f(x,key))) for x in candles[-24:]]
    m=sum(a)/24.0
    sd=math.sqrt(sum((x-m)**2 for x in a)/24.0)
    return 0.0 if sd==0 else (a[-1]-m)/sd

def feature_values(candles):
    if len(candles)<169: raise ValueError("169 closed 1h candles required")
    x=candles[-169:]
    c=[_f(r,"close") for r in x]
    last=x[-1]
    ds=[c[i]-c[i-1] for i in range(len(c)-14,len(c))]
    gain=sum(max(v,0.0) for v in ds)/14.0
    loss=sum(max(-v,0.0) for v in ds)/14.0
    rsi=1.0 if loss==0 else 1.0-1.0/(1.0+gain/loss)
    lr=[math.log(c[i]/c[i-1]) for i in range(len(c)-24,len(c))]
    lm=sum(lr)/24.0
    rv=100.0*math.sqrt(sum((v-lm)**2 for v in lr)/24.0)
    rng=_f(last,"high")-_f(last,"low")
    close_loc=0.0 if rng==0 else 2.0*(_f(last,"close")-_f(last,"low"))/rng-1.0
    hi=max(_f(r,"high") for r in x[-24:])
    lo=min(_f(r,"low") for r in x[-24:])
    e20=_ema(c,20); e50=_ema(c,50)
    imb1=_imb(x,1); imb4=_imb(x,4); imb24=_imb(x,24)
    values=[
      _ret(c,1),_ret(c,3),_ret(c,6),_ret(c,24),_ret(c,72),
      100.0*(c[-1]/e20-1.0),100.0*(e20/e50-1.0),rsi,rv,
      100.0*rng/c[-1],close_loc,100.0*(c[-1]/hi-1.0),100.0*(c[-1]/lo-1.0),
      _zlog(x,"volume"),_zlog(x,"trades"),imb1,imb4,imb24,imb1-imb24
    ]
    if any(not math.isfinite(float(v)) for v in values): raise ValueError("non-finite 1h feature")
    return values

def forecast_1h(candles,artifact=None):
    a=artifact or frozen_artifact()
    e=a["horizons"]["1h"]
    if e["features"]!=FEATURES: raise ValueError("frozen 1h feature order mismatch")
    values=feature_values(candles)
    z=[(float(v)-float(m))/float(s) for v,m,s in zip(values,e["means"],e["scales"])]
    if max(map(abs,z))>float(e.get("max_abs_feature_z",4.0)):
        return {"status":"ABSTAIN_MODEL_DRIFT","probabilities":None,
                "max_abs_feature_z":max(map(abs,z))}
    p=calibrated_candidate_probabilities(e,z)
    return {"status":"CANDIDATE_ONLY_PROSPECTIVE_SHADOW",
            "probabilities":dict(zip(("upside","range","downside"),[round(v,6) for v in p])),
            "feature_hash":hashlib.sha256(json.dumps(values,separators=(",",":")).encode()).hexdigest(),
            "max_abs_feature_z":max(map(abs,z))}
