"""Mac read-only historical market collector for GitHub research; no keys/payments.

The resulting compressed raw is NOT signed at capture time by GitHub. Its
collection provenance stays explicit. GitHub later hashes and signs the
transported bytes. Historical OI snapshots cannot prove vendor publication lag.
"""
import datetime as dt
import gzip
import hashlib
import json
import pathlib
import time
import urllib.request
import urllib.parse
import urllib.error

UTC=dt.timezone.utc
START=int(dt.datetime(2026,9,14,tzinfo=UTC).timestamp()*1000)
END=int(dt.datetime(2026,10,11,18,55,tzinfo=UTC).timestamp()*1000)
STEP=300000

def get(url):
    for attempt in range(5):
        try:
            req=urllib.request.Request(url,headers={"User-Agent":"btc-vnext6-mac-readonly-collector"})
            with urllib.request.urlopen(req,timeout=30) as r:
                if r.status!=200:raise RuntimeError("market HTTP "+str(r.status))
                return json.load(r)
        except (urllib.error.URLError,TimeoutError) as e:
            if attempt==4:raise
            time.sleep(1.5*(attempt+1))

def collect_oi(endpoint,other):
    data={}
    cursor=START
    while cursor<END:
        top=min(cursor+499*STEP,END)
        query={**other,"period":"5m","limit":500,"startTime":cursor,"endTime":top}
        j=get(endpoint+"?"+urllib.parse.urlencode(query))
        if not isinstance(j,list) or not j:raise ValueError("missing OI page "+str(cursor))
        for x in j:
            ts=int(x["timestamp"]);val=float(x["sumOpenInterestValue"])
            if START<=ts<=END:
                if val<=0:raise ValueError("non-positive OI")
                if ts in data and data[ts]!=val:raise ValueError("duplicate changed OI")
                data[ts]=val
        cursor=top+STEP
        time.sleep(0.15)
    if len(data)<6500:raise ValueError("incomplete historical OI "+str(len(data)))
    return data

def main():
    um=collect_oi("https://fapi.binance.com/futures/data/openInterestHist",{"symbol":"BTCUSDT"})
    cm=collect_oi("https://dapi.binance.com/futures/data/openInterestHist",{"pair":"BTCUSD","contractType":"PERPETUAL"})
    f=get("https://fapi.binance.com/fapi/v1/fundingRate?"+urllib.parse.urlencode({
        "symbol":"BTCUSDT","limit":1000,"startTime":START-86400000,"endTime":END
    }))
    funding={int(x["fundingTime"]):float(x["fundingRate"]) for x in f}
    if len(funding)<65:raise ValueError("funding incomplete")
    data={"schema":"btc-vnext6-historical-futures-mac-collector-v1",
          "collector":"authorized_user_Mac_via_Desktop_Commander",
          "retrieved_at_utc":dt.datetime.now(UTC).isoformat(),
          "source_urls":{
              "um":"https://fapi.binance.com/futures/data/openInterestHist",
              "cm":"https://dapi.binance.com/futures/data/openInterestHist",
              "funding":"https://fapi.binance.com/fapi/v1/fundingRate",
          },
          "warning":"historical vendor timestamps; not independent proof of point-in-time availability",
          "um":um,"cm":cm,"funding":funding}
    raw=json.dumps(data,sort_keys=True,separators=(",",":"),allow_nan=False).encode()
    out=pathlib.Path("btc_skill_rebuild/raw/oi_funding_20260914_20261011.json.gz")
    out.parent.mkdir(parents=True,exist_ok=True)
    with out.open("wb") as f:
        with gzip.GzipFile(fileobj=f,mode="wb",mtime=0) as z:z.write(raw)
    print(json.dumps({
        "path":str(out),"uncompressed_sha256":hashlib.sha256(raw).hexdigest(),
        "compressed_sha256":hashlib.sha256(out.read_bytes()).hexdigest(),
        "um":len(um),"cm":len(cm),"funding":len(funding),
        "first_um":min(um),"last_um":max(um)},sort_keys=True))
if __name__=="__main__":main()
