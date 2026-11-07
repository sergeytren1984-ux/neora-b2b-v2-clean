"""Fetch monthly public Binance spot klines, keeping provenance per archive.

Research input only. No missing month or incomplete candle is silently filled.
"""
import concurrent.futures
import csv
import datetime as dt
import gzip
import hashlib
import io
import json
import urllib.request
import zipfile
from pathlib import Path

START=(2024,1);END=(2026,6)
months=[];year,month=START
while (year,month)<=END:
    months.append(f"{year:04d}-{month:02d}")
    month+=1
    if month==13:year+=1;month=1

def one(item):
    interval,month=item
    url=f"https://data.binance.vision/data/spot/monthly/klines/BTCUSDT/{interval}/BTCUSDT-{interval}-{month}.zip"
    with urllib.request.urlopen(urllib.request.Request(url,headers={"User-Agent":"btc-predictive-research"}),timeout=45) as f:
        archive=f.read()
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        names=z.namelist()
        if len(names)!=1:raise ValueError((url,names))
        rows=list(csv.reader(io.StringIO(z.read(names[0]).decode())))
    # Binance changed time unit in archive in 2025; normalize microseconds to ms.
    for row in rows:
        if int(row[0])>10**14:
            row[0]=str(int(row[0])//1000);row[6]=str(int(row[6])//1000)
    return interval,month,rows,{"url":url,"archive_sha256":hashlib.sha256(archive).hexdigest(),"rows":len(rows)}

if __name__=='__main__':
    target=Path('research_vnext/data');target.mkdir(exist_ok=True)
    groups={'5m':[], '15m':[]};manifest={}
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        for interval,month,rows,entry in pool.map(one,[(i,m) for i in groups for m in months]):
            groups[interval].extend(rows);manifest[f'{interval}/{month}']=entry
            print(interval,month,len(rows),flush=True)
    for interval,rows in groups.items():
        period={'5m':300000,'15m':900000}[interval]
        rows.sort(key=lambda x:int(x[0]));t=[int(x[0]) for x in rows]
        if len(t)!=len(set(t)) or any(b-a!=period for a,b in zip(t,t[1:])):
            raise ValueError(f'Missing/duplicate {interval} candles')
        if any(int(x[6]) != int(x[0])+period-1 for x in rows):
            raise ValueError(f'Partial {interval} candle')
        output=target/f'BTCUSDT_{interval}_2024-01_2026-06.json.gz'
        with gzip.open(output,'wt') as f:json.dump(rows,f,separators=(',',':'))
        manifest[interval+'_combined']={'rows':len(rows),'sha256':hashlib.sha256(output.read_bytes()).hexdigest(),
                                         'first_ms':t[0],'last_ms':t[-1]}
    (target/'manifest.json').write_text(json.dumps(manifest,indent=2))
