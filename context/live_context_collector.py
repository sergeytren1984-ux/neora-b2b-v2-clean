from __future__ import annotations
import base64, hashlib, json, re, urllib.request, urllib.parse
from datetime import datetime, timezone
from pathlib import Path

UTC=timezone.utc
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"context_live"
UA="Mozilla/5.0 BTC-context-evidence/3.0"

QUOTE_MAX_AGE_SECONDS={
    "funding":900,
    "open_interest":900,
    "dxy":1800,
    "nasdaq_futures":1800,
    "us10y":1800,
}
ETF_MAX_COMPLETE_SESSION_AGE_DAYS=4

def now(): return datetime.now(UTC)
def iso_ms(ms): return datetime.fromtimestamp(int(ms)/1000,UTC).isoformat()
def sha(b): return hashlib.sha256(b).hexdigest()

def fetch(url, timeout=12):
    req=urllib.request.Request(url,headers={"User-Agent":UA,"Accept":"*/*"})
    with urllib.request.urlopen(req,timeout=timeout) as r:
        b=r.read(2_000_001)
        if len(b)>2_000_000: raise ValueError("response too large")
        return {
            "requested_url":url,
            "final_url":r.geturl(),
            "http_status":r.status,
            "retrieved_at_utc":now().isoformat(),
            "sha256":sha(b),
            "raw":b.decode("utf-8","replace"),
            "raw_response_b64":base64.b64encode(b).decode("ascii"),
        }

def receipt(x):
    return {k:x[k] for k in (
        "requested_url","final_url","http_status","retrieved_at_utc",
        "sha256","raw_response_b64"
    )}

def first_success(name, attempts):
    errors=[]
    for source,fn in attempts:
        try:
            v=fn()
            v["status"]="VALID"
            v["source"]=source
            if errors:
                v["failed_attempts_before_success"]=errors
            return v
        except Exception as e:
            errors.append({"source":source,"error":(type(e).__name__+": "+str(e))[:240]})
    return {"status":"UNAVAILABLE","factor":name,"errors":errors}

def binance_funding():
    x=fetch("https://fapi.binance.com/fapi/v1/premiumIndex?symbol=BTCUSDT")
    j=json.loads(x["raw"])
    return {"value":float(j["lastFundingRate"]),"unit":"fraction_per_8h",
            "source_timestamp_utc":iso_ms(j["time"]),"receipt":receipt(x)}

def okx_funding():
    x=fetch("https://www.okx.com/api/v5/public/funding-rate?instId=BTC-USDT-SWAP")
    j=json.loads(x["raw"])["data"][0]
    return {"value":float(j["fundingRate"]),"unit":"fraction_per_period",
            "source_timestamp_utc":iso_ms(j["ts"]),
            "funding_time_utc":iso_ms(j["fundingTime"]),"receipt":receipt(x)}

def binance_oi():
    x=fetch("https://fapi.binance.com/fapi/v1/openInterest?symbol=BTCUSDT")
    j=json.loads(x["raw"])
    return {"value":float(j["openInterest"]),"unit":"BTC_contract_units",
            "exchange":"Binance USD-M","source_timestamp_utc":iso_ms(j["time"]),
            "receipt":receipt(x)}

def okx_oi():
    x=fetch("https://www.okx.com/api/v5/public/open-interest?instType=SWAP&instId=BTC-USDT-SWAP")
    j=json.loads(x["raw"])["data"][0]
    return {"value_btc":float(j["oiCcy"]),"value_usd":float(j["oiUsd"]),
            "unit":"BTC_and_USD","exchange":"OKX BTC-USDT-SWAP",
            "source_timestamp_utc":iso_ms(j["ts"]),"receipt":receipt(x)}

def yahoo(symbol):
    q=urllib.parse.quote(symbol,safe="")
    x=fetch(f"https://query1.finance.yahoo.com/v8/finance/chart/{q}?interval=5m&range=1d&includePrePost=true")
    z=json.loads(x["raw"])["chart"]["result"][0]; meta=z["meta"]
    pts=[(t,v) for t,v in zip(z.get("timestamp",[]),z["indicators"]["quote"][0]["close"]) if v is not None]
    if not pts: raise ValueError("no non-null quotes")
    t,v=pts[-1]
    return {"value":float(v),"previous_close":meta.get("previousClose"),
            "unit":"index_or_yield",
            "source_timestamp_utc":datetime.fromtimestamp(t,UTC).isoformat(),
            "receipt":receipt(x)}

def _flow_number(text):
    s=re.sub(r"<[^>]+>","",text).replace("&nbsp;"," ").strip().replace(",","")
    if s in ("","-"): return None
    neg=s.startswith("(") and s.endswith(")")
    if neg: s=s[1:-1]
    v=float(s)
    return -v if neg else v

def farside_raw():
    x=fetch("https://farside.co.uk/btc/")
    html=x["raw"]
    rows=re.findall(r"<tr[^>]*>(.*?)</tr>",html,flags=re.I|re.S)
    parsed=[]
    for row in rows:
        cells=re.findall(r"<td[^>]*>(.*?)</td>",row,flags=re.I|re.S)
        if len(cells)<3: continue
        date_txt=re.sub(r"<[^>]+>","",cells[0]).strip()
        if not re.fullmatch(r"\d{1,2} [A-Z][a-z]{2} 20\d{2}",date_txt): continue
        vals=[_flow_number(x) for x in cells[1:]]
        if not vals or any(v is None for v in vals): continue
        parsed.append((datetime.strptime(date_txt,"%d %b %Y").replace(tzinfo=UTC),vals))
    if not parsed: raise ValueError("no fully populated Farside daily row")
    dt,vals=max(parsed,key=lambda z:z[0])
    return {"numeric_value":float(vals[-1]),"unit":"USD_millions",
            "flow_date_utc":dt.date().isoformat(),
            "constituent_values":vals[:-1],"receipt":receipt(x)}

def apply_freshness(name,factor,at):
    if factor.get("status")!="VALID":
        factor["freshness_status"]="UNAVAILABLE"
        return factor
    if name=="etf_flows":
        d=datetime.fromisoformat(factor["flow_date_utc"]+"T00:00:00+00:00").date()
        age_days=(at.date()-d).days
        factor["age_days"]=age_days
        factor["max_age_days"]=ETF_MAX_COMPLETE_SESSION_AGE_DAYS
        factor["freshness_status"]="LATEST_COMPLETE_SESSION" if 0<=age_days<=ETF_MAX_COMPLETE_SESSION_AGE_DAYS else "STALE"
        return factor
    stamp=factor.get("source_timestamp_utc")
    if not stamp:
        factor["freshness_status"]="MISSING_TIMESTAMP"
        return factor
    src=datetime.fromisoformat(stamp.replace("Z","+00:00")).astimezone(UTC)
    age=(at-src).total_seconds()
    max_age=QUOTE_MAX_AGE_SECONDS[name]
    factor["age_seconds"]=round(age,3)
    factor["max_age_seconds"]=max_age
    factor["freshness_status"]="FRESH" if -60<=age<=max_age else "STALE"
    return factor

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
      "funding":first_success("funding",[
          ("BINANCE_USDM",binance_funding),("OKX_SWAP",okx_funding)]),
      "open_interest":first_success("open_interest",[
          ("BINANCE_USDM",binance_oi),("OKX_SWAP",okx_oi)]),
      "dxy":first_success("dxy",[
          ("YAHOO_DX-Y.NYB",lambda:yahoo("DX-Y.NYB"))]),
      "nasdaq_futures":first_success("nasdaq_futures",[
          ("YAHOO_NQ=F",lambda:yahoo("NQ=F"))]),
      "us10y":first_success("us10y",[
          ("YAHOO_^TNX",lambda:yahoo("^TNX"))]),
      "etf_flows":first_success("etf_flows",[
          ("FARSIDE",farside_raw)]),
    }
    for name in list(factors):
        factors[name]=apply_freshness(name,factors[name],t)

    fresh_ok=all(
        factors[k].get("status")=="VALID" and
        factors[k].get("freshness_status") in ("FRESH","LATEST_COMPLETE_SESSION")
        for k in factors
    )
    doc={
      "schema":"btc-live-context-v3",
      "captured_at_utc":t.isoformat(),
      "numeric_core":"v2.9.30-frozen-unchanged",
      "raw_responses_embedded":True,
      "factors":factors,
      "calendar":calendar_context(t),
      "admission":{
        "context_complete":fresh_ok,
        "freshness_enforced":True,
        "numeric_challenger_authorized":False,
        "reason":"context is signed reproducible evidence only until exogenous challenger passes validation",
      },
    }
    OUT.mkdir(exist_ok=True)
    name=t.strftime("%Y%m%dT%H%M%S")+"Z.json"
    p=OUT/name
    p.write_text(json.dumps(doc,sort_keys=True,separators=(",",":"),ensure_ascii=False)+"\n")
    print(str(p.relative_to(ROOT)))

if __name__=="__main__":
    main()
