"""Fetch R6 15m Binance spot history through 2026-09 with per-archive hashes."""
from __future__ import annotations
import concurrent.futures,csv,datetime as dt,gzip,hashlib,io,json,urllib.request,zipfile
from pathlib import Path

START=(2024,1);END=(2026,9)
months=[];y,m=START
while (y,m)<=END:
    months.append(f"{y:04d}-{m:02d}")
    m+=1
    if m==13:y+=1;m=1

def one(month):
    interval="15m"
    url=f"https://data.binance.vision/data/spot/monthly/klines/BTCUSDT/{interval}/BTCUSDT-{interval}-{month}.zip"
    req=urllib.request.Request(url,headers={"User-Agent":"btc-predictive-r6-research"})
    with urllib.request.urlopen(req,timeout=45) as f: archive=f.read()
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        names=z.namelist()
        if len(names)!=1: raise ValueError((url,names))
        rows=list(csv.reader(io.StringIO(z.read(names[0]).decode())))
    for row in rows:
        if int(row[0])>10**14:
            row[0]=str(int(row[0])//1000);row[6]=str(int(row[6])//1000)
    return month,rows,{"url":url,"archive_sha256":hashlib.sha256(archive).hexdigest(),"rows":len(rows)}

def main():
    target=Path("research_vnext4r6/data");target.mkdir(parents=True,exist_ok=True)
    rows=[];manifest={}
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        for month,batch,entry in pool.map(one,months):
            rows.extend(batch);manifest[month]=entry
            print(month,len(batch),flush=True)
    rows.sort(key=lambda x:int(x[0]));t=[int(x[0]) for x in rows];period=900000
    if len(t)!=len(set(t)) or any(b-a!=period for a,b in zip(t,t[1:])):
        raise ValueError("missing/duplicate 15m candles")
    if any(int(x[6])!=int(x[0])+period-1 for x in rows):
        raise ValueError("partial 15m candle")
    raw=json.dumps(rows,separators=(",",":")).encode()
    blob=gzip.compress(raw,compresslevel=9,mtime=0)
    out=target/"BTCUSDT_15m_2024-01_2026-09.json.gz";out.write_bytes(blob)
    doc={
      "schema":"btc-predictive-r6-15m-history-manifest-v1",
      "archive_count":len(manifest),"archives":manifest,
      "combined":{"rows":len(rows),"compressed_sha256":hashlib.sha256(blob).hexdigest(),
                  "logical_sha256":hashlib.sha256(raw).hexdigest(),
                  "first_ms":t[0],"last_ms":t[-1]},
    }
    (target/"BTCUSDT_15m_2024-01_2026-09.manifest.json").write_text(
      json.dumps(doc,indent=2,sort_keys=True)+"\n")
    print(json.dumps(doc["combined"],sort_keys=True))

if __name__=="__main__":
    main()
