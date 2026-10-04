"""One-off live diagnostic using the exact frozen vNext4 numerical artifacts.

This is NOT part of the vNext4R2 prospective ledger and cannot be used for
admission. It exists only to answer the operator's current market question.
"""
from __future__ import annotations
import json, math, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path
import joblib, numpy as np

from predictive_vnext4.live_features import hourly_feature, early15m_feature
from predictive_vnext4.predict import predict_contenders, control_prediction

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"research_vnext4/live_diagnostic.json"
UTC=timezone.utc

def get(url):
    req=urllib.request.Request(url,headers={"User-Agent":"btc-vnext4-live-diagnostic"})
    with urllib.request.urlopen(req,timeout=25) as r:
        return json.loads(r.read())

def klines(interval,limit=1000):
    q=urllib.parse.urlencode({"symbol":"BTCUSDT","interval":interval,"limit":limit})
    rows=get("https://data-api.binance.vision/api/v3/klines?"+q)
    now_ms=int(datetime.now(UTC).timestamp()*1000)
    return [x for x in rows if int(x[6])<now_ms]

def arrays(rows):
    return tuple(np.asarray([float(x[j]) for x in rows]) for j in (2,3,4,5,8,9))

def pct(a,b): return (b/a-1)*100

def spot_stats(rows):
    c=np.asarray([float(x[4]) for x in rows])
    v=np.asarray([float(x[5]) for x in rows])
    tak=np.asarray([float(x[9]) for x in rows])
    trades=np.asarray([float(x[8]) for x in rows])
    return {
      "last_close":float(c[-1]),
      "ret_1h_pct":pct(c[-2],c[-1]),
      "ret_4h_pct":pct(c[-5],c[-1]),
      "ret_24h_pct":pct(c[-25],c[-1]),
      "range_24h_pct":float((max(float(x[2]) for x in rows[-24:])/min(float(x[3]) for x in rows[-24:])-1)*100),
      "volume_last_vs_prev24_mean":float(v[-1]/max(np.mean(v[-25:-1]),1e-12)),
      "trades_last_vs_prev24_mean":float(trades[-1]/max(np.mean(trades[-25:-1]),1e-12)),
      "taker_buy_ratio_last":float(tak[-1]/max(v[-1],1e-12)),
      "taker_buy_ratio_4h":float(np.sum(tak[-4:])/max(np.sum(v[-4:]),1e-12)),
      "taker_buy_ratio_24h":float(np.sum(tak[-24:])/max(np.sum(v[-24:]),1e-12)),
      "high_24h":float(max(float(x[2]) for x in rows[-24:])),
      "low_24h":float(min(float(x[3]) for x in rows[-24:])),
    }

def futures():
    out={}
    endpoints={
      "premium":"https://fapi.binance.com/fapi/v1/premiumIndex?symbol=BTCUSDT",
      "oi":"https://fapi.binance.com/fapi/v1/openInterest?symbol=BTCUSDT",
      "oi_hist":"https://fapi.binance.com/futures/data/openInterestHist?symbol=BTCUSDT&period=1h&limit=25",
      "taker":"https://fapi.binance.com/futures/data/takerlongshortRatio?symbol=BTCUSDT&period=1h&limit=24",
    }
    for k,u in endpoints.items():
        try: out[k]=get(u)
        except Exception as e: out[k]={"error":type(e).__name__+":"+str(e)[:160]}
    return out

def main():
    now=datetime.now(UTC)
    hrows=klines("1h"); erows=klines("15m")
    hhi,hlo,hc,hv,htr,htk=arrays(hrows)
    ehi,elo,ec,ev,etr,etk=arrays(erows)
    hx,hmeta=hourly_feature(hhi,hlo,hc,hv,htr,htk)
    ex,emeta=early15m_feature(ehi,elo,ec,ev,etr,etk)
    ha=joblib.load(ROOT/"predictive_vnext4/hourly_contenders.joblib")
    ea=joblib.load(ROOT/"predictive_vnext4/early15m_contenders.joblib")
    hp=predict_contenders(ha,hx)
    ep=predict_contenders(ea,ex)
    hc0=control_prediction(ha,hmeta["rv24"],now.isoformat(),[])
    ec0=control_prediction(ea,emeta["rv4h"],now.isoformat(),[])
    hdist=hmeta["reference_price"]*hmeta["rv24"]*math.sqrt(72)
    result={
      "schema":"btc-vnext4-oneoff-live-diagnostic-v1",
      "generated_at_utc":now.isoformat(),
      "status":"NON_PROSPECTIVE_OPERATOR_DIAGNOSTIC",
      "not_for_admission":True,
      "hourly":{
        "reference":hmeta["reference_price"],
        "rv24":hmeta["rv24"],
        "lower":hmeta["reference_price"]-hdist,
        "upper":hmeta["reference_price"]+hdist,
        "predictions":hp,"control":hc0,
        "spot":spot_stats(hrows),
      },
      "early15m":{
        "reference":emeta["reference_price"],
        "rv4h":emeta["rv4h"],
        "lower":emeta["reference_price"]*.99,
        "upper":emeta["reference_price"]*1.01,
        "predictions":ep,"control":ec0,
        "spot":spot_stats(erows),
      },
      "futures":futures()
    }
    # compact derivative summary if available
    oi=result["futures"].get("oi_hist")
    if isinstance(oi,list) and len(oi)>=2:
        a=float(oi[0]["sumOpenInterestValue"]);b=float(oi[-1]["sumOpenInterestValue"])
        result["futures_summary"]={"oi_value_24h_change_pct":pct(a,b)}
        tak=result["futures"].get("taker")
        if isinstance(tak,list) and tak:
            vals=[float(x["buySellRatio"]) for x in tak]
            result["futures_summary"]["taker_buy_sell_ratio_mean_24h"]=float(np.mean(vals))
            result["futures_summary"]["taker_buy_sell_ratio_last"]=float(vals[-1])
    prem=result["futures"].get("premium")
    if isinstance(prem,dict) and "lastFundingRate" in prem:
        result.setdefault("futures_summary",{})["funding_rate"]=float(prem["lastFundingRate"])
        result["futures_summary"]["mark_price"]=float(prem["markPrice"])
    oi0=result["futures"].get("oi")
    if isinstance(oi0,dict) and "openInterest" in oi0:
        result.setdefault("futures_summary",{})["open_interest_contracts"]=float(oi0["openInterest"])
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2,sort_keys=True)+"\n")
    print(json.dumps(result,ensure_ascii=False,indent=2,sort_keys=True))

if __name__=="__main__": main()
