"""Fetch reproducible public exogenous research inputs for R6.

Research-only. Daily Yahoo observations are NOT treated as available at their raw
timestamp. The downstream ablation applies a full 24h availability lag to avoid
using a daily close before it could have been observed.

Farside rows are stored raw/parsed; downstream availability is conservatively the
following calendar day at 12:00 UTC. Missing ETF history is never filled.
"""
from __future__ import annotations
import hashlib,json,re,time,urllib.parse,urllib.request
from datetime import datetime,timezone
from pathlib import Path

UTC=timezone.utc
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"research_vnext4r6"
UA="btc-predictive-r6-research/1.0"
START=int(datetime(2023,12,15,tzinfo=UTC).timestamp())
END=int(datetime(2026,10,1,tzinfo=UTC).timestamp())


def get(url,timeout=30):
    req=urllib.request.Request(url,headers={"User-Agent":UA,"Accept":"*/*"})
    with urllib.request.urlopen(req,timeout=timeout) as r:
        b=r.read()
    return b,hashlib.sha256(b).hexdigest()


def yahoo(symbol):
    q=urllib.parse.quote(symbol,safe="")
    url=(f"https://query1.finance.yahoo.com/v8/finance/chart/{q}"
         f"?period1={START}&period2={END}&interval=1d&events=history&includeAdjustedClose=true")
    b,digest=get(url)
    z=json.loads(b)["chart"]["result"][0]
    ts=z.get("timestamp") or []
    close=((z.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
    pts=[{"timestamp_utc":datetime.fromtimestamp(int(t),UTC).isoformat(),"close":float(v)}
         for t,v in zip(ts,close) if v is not None]
    if len(pts)<400: raise ValueError(f"insufficient Yahoo history {symbol}: {len(pts)}")
    return {"symbol":symbol,"source_url":url,"raw_sha256":digest,"points":pts}


def flow_number(text):
    s=re.sub(r"<[^>]+>","",text).replace("&nbsp;"," ").strip().replace(",","")
    if s in ("","-"): return None
    neg=s.startswith("(") and s.endswith(")")
    if neg:s=s[1:-1]
    v=float(s)
    return -v if neg else v


def farside():
    url="https://farside.co.uk/btc/"
    b,digest=get(url)
    html=b.decode("utf-8","replace")
    rows=[]
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>",html,flags=re.I|re.S):
        cells=re.findall(r"<td[^>]*>(.*?)</td>",row,flags=re.I|re.S)
        if len(cells)<3:continue
        d=re.sub(r"<[^>]+>","",cells[0]).strip()
        if not re.fullmatch(r"\d{1,2} [A-Z][a-z]{2} 20\d{2}",d):continue
        vals=[flow_number(x) for x in cells[1:]]
        if not vals or any(v is None for v in vals):continue
        dt=datetime.strptime(d,"%d %b %Y").replace(tzinfo=UTC)
        rows.append({"date":dt.date().isoformat(),"total_usd_millions":float(vals[-1])})
    rows.sort(key=lambda x:x["date"])
    return {"source_url":url,"raw_sha256":digest,"rows":rows}


def main():
    doc={
      "schema":"btc-predictive-r6-exogenous-history-v1",
      "retrieved_at_utc":datetime.now(UTC).isoformat(),
      "availability_policy":{
        "yahoo_daily":"raw point + 24h",
        "farside_daily":"flow date + 1 calendar day at 12:00 UTC",
        "missing_values":"reject/not available; never forward-fill beyond actual latest observation",
      },
      "series":{
        "dxy":yahoo("DX-Y.NYB"),
        "nasdaq_futures":yahoo("NQ=F"),
        "us10y":yahoo("^TNX"),
        "etf_flows":farside(),
      }
    }
    OUT.mkdir(exist_ok=True)
    p=OUT/"macro_history.json"
    p.write_text(json.dumps(doc,ensure_ascii=False,indent=2,sort_keys=True)+"\n")
    print(json.dumps({k:(len(v.get("points",[])) or len(v.get("rows",[])))
                      for k,v in doc["series"].items()},sort_keys=True))


if __name__=="__main__":
    main()
