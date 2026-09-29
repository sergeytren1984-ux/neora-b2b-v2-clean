from __future__ import annotations
import hashlib, json, os, urllib.request, urllib.parse
from datetime import datetime, timezone
from pathlib import Path

UTC=timezone.utc
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"context_live"
UA="Mozilla/5.0 BTC-context-evidence/2.0"

def now(): return datetime.now(UTC)
def iso_ms(ms): return datetime.fromtimestamp(int(ms)/1000,UTC).isoformat()
def sha(b): return hashlib.sha256(b).hexdigest()

def fetch(url, timeout=12):
    req=urllib.request.Request(url,headers={"User-Agent":UA,"Accept":"*/*"})
    with urllib.request.urlopen(req,timeout=timeout) as r:
        b=r.read(2_000_001)
        if len(b)>2_000_000: raise ValueError("response too large")
        return {"requested_url":url,"final_url":r.geturl(),"status":r.status,
                "retrieved_at_utc":now().isoformat(),"sha256":sha(b),"raw":b.decode("utf-8","replace")}

def first_success(name, attempts):
    errors=[]
    for source,fn in attempts:
        try:
            v=fn()
            v["status"]="VALID"
            v["source"]=source
            return v
        except Exception as e:
            errors.append({"source":source,"error":(type(e).__name__+": "+str(e))[:240]})
    return {"status":"UNAVAILABLE","factor":name,"errors":errors}

def binance_funding():
    x=fetch("https://fapi.binance.com/fapi/v1/premiumIndex?symbol=BTCUSDT")
    j=json.loads(x["raw"])
    return {"value":float(j["lastFundingRate"]),"unit":"fraction_per_8h",
            "source_timestamp_utc":iso_ms(j["time"]),"receipt":{k:x[k] for k in ("requested_url","final_url","retrieved_at_utc","sha256")}}

def okx_funding():
    x=fetch("https://www.okx.com/api/v5/public/funding-rate?instId=BTC-USDT-SWAP")
    j=json.loads(x["raw"])["data"][0]
    return {"value":float(j["fundingRate"]),"unit":"fraction_per_period",
            "source_timestamp_utc":iso_ms(j["ts"]),"funding_time_utc":iso_ms(j["fundingTime"]),
            "receipt":{k:x[k] for k in ("requested_url","final_url","retrieved_at_utc","sha256")}}

def binance_oi():
    x=fetch("https://fapi.binance.com/fapi/v1/openInterest?symbol=BTCUSDT")
    j=json.loads(x["raw"])
    return {"value":float(j["openInterest"]),"unit":"BTC_contract_units",
            "source_timestamp_utc":iso_ms(j["time"]),"receipt":{k:x[k] for k in ("requested_url","final_url","retrieved_at_utc","sha256")}}

def okx_oi():
    x=fetch("https://www.okx.com/api/v5/public/open-interest?instType=SWAP&instId=BTC-USDT-SWAP")
    j=json.loads(x["raw"])["data"][0]
    return {"value_btc":float(j["oiCcy"]),"value_usd":float(j["oiUsd"]),"unit":"BTC_and_USD",
            "source_timestamp_utc":iso_ms(j["ts"]),"receipt":{k:x[k] for k in ("requested_url","final_url","retrieved_at_utc","sha256")}}

def yahoo(symbol):
    q=urllib.parse.quote(symbol,safe="")
    x=fetch(f"https://query1.finance.yahoo.com/v8/finance/chart/{q}?interval=5m&range=1d&includePrePost=true")
    z=json.loads(x["raw"])["chart"]["result"][0]; meta=z["meta"]
    pts=[(t,v) for t,v in zip(z.get("timestamp",[]),z["indicators"]["quote"][0]["close"]) if v is not None]
    if not pts: raise ValueError("no non-null quotes")
    t,v=pts[-1]
    return {"value":float(v),"previous_close":meta.get("previousClose"),"unit":"index_or_yield",
            "source_timestamp_utc":datetime.fromtimestamp(t,UTC).isoformat(),
            "receipt":{k:x[k] for k in ("requested_url","final_url","retrieved_at_utc","sha256")}}

def farside_raw():
    x=fetch("https://farside.co.uk/btc/")
    return {"status":"RAW_ONLY","numeric_value":None,"unit":"USD_millions",
            "note":"raw official table captured; parser intentionally withheld unless table schema validates",
            "receipt":{k:x[k] for k in ("requested_url","final_url","retrieved_at_utc","sha256")}}

def calendar_context(at):
    p=ROOT/"context"/"macro_calendar_seed_2026q4.json"
    if not p.exists(): return {"status":"UNAVAILABLE","events":[]}
    doc=json.loads(p.read_text())
    out=[]
    for e in doc.get("events",[]):
        t=datetime.fromisoformat(e["scheduled_utc"].replace("Z","+00:00")).astimezone(UTC)
        mins=(t-at).total_seconds()/60
        if -240 <= mins <= 1440:
            out.append({**e,"minutes_from_snapshot":round(mins,2)})
    return {"status":"VALID","events":out}

def main():
    t=now()
    factors={
      "funding":first_success("funding",[("BINANCE_USDM",binance_funding),("OKX_SWAP",okx_funding)]),
      "open_interest":first_success("open_interest",[("BINANCE_USDM",binance_oi),("OKX_SWAP",okx_oi)]),
      "dxy":first_success("dxy",[("YAHOO_DX-Y.NYB",lambda:yahoo("DX-Y.NYB"))]),
      "nasdaq_futures":first_success("nasdaq_futures",[("YAHOO_NQ=F",lambda:yahoo("NQ=F"))]),
      "us10y":first_success("us10y",[("YAHOO_^TNX",lambda:yahoo("^TNX"))]),
      "etf_flows":first_success("etf_flows",[("FARSIDE",farside_raw)])
    }
    doc={"schema":"btc-live-context-v2","captured_at_utc":t.isoformat(),
         "numeric_core":"v2.9.30-frozen-unchanged","factors":factors,
         "calendar":calendar_context(t),
         "admission":{"context_complete":all(factors[k].get("status") in ("VALID","RAW_ONLY") for k in factors),
                      "numeric_challenger_authorized":False,
                      "reason":"context is evidence only until exogenous challenger passes validation"}}
    OUT.mkdir(exist_ok=True)
    name=t.strftime("%Y%m%dT%H%M%S")+"Z.json"
    p=OUT/name
    p.write_text(json.dumps(doc,sort_keys=True,separators=(",",":"),ensure_ascii=False)+"\n")
    print(str(p.relative_to(ROOT)))

if __name__=="__main__":
    main()
