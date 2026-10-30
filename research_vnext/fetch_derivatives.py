"""Fetch public Binance USD-M BTCUSDT OI metrics and settled funding with hashes."""
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

start=dt.date(2024,1,1);end=dt.date(2026,6,30)
days=[start+dt.timedelta(days=i) for i in range((end-start).days+1)]
months=sorted({d.strftime('%Y-%m') for d in days})

def fetch(item):
    kind,key=item
    if kind=='oi':url=f'https://data.binance.vision/data/futures/um/daily/metrics/BTCUSDT/BTCUSDT-metrics-{key}.zip'
    else:url=f'https://data.binance.vision/data/futures/um/monthly/fundingRate/BTCUSDT/BTCUSDT-fundingRate-{key}.zip'
    with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'btc-predictive-research'}),timeout=40) as f:archive=f.read()
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        if len(z.namelist())!=1:raise ValueError(url)
        rows=list(csv.DictReader(io.StringIO(z.read(z.namelist()[0]).decode())))
    return kind,key,rows,{'url':url,'sha256':hashlib.sha256(archive).hexdigest(),'rows':len(rows)}

if __name__=='__main__':
    target=Path('research_vnext/data');target.mkdir(exist_ok=True)
    groups={'oi':[],'funding':[]};manifest={}
    items=[('oi',str(d)) for d in days]+[('funding',m) for m in months]
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        for j,(kind,key,rows,entry) in enumerate(pool.map(fetch,items),1):
            groups[kind].extend(rows);manifest[f'{kind}/{key}']=entry
            if j%100==0:print(j,'/',len(items),flush=True)
    for kind,rows in groups.items():
        field='create_time' if kind=='oi' else 'calc_time'
        print(kind,len(rows),list(rows[0]),rows[0],flush=True)
        # Keep raw source rows to prevent accidental reinterpretation of units.
        output=target/f'BTCUSDT_{kind}_2024-01_2026-06.json.gz'
        with gzip.open(output,'wt') as f:json.dump(rows,f,separators=(',',':'))
        manifest[kind+'_combined']={'rows':len(rows),'sha256':hashlib.sha256(output.read_bytes()).hexdigest()}
    (target/'derivatives_manifest.json').write_text(json.dumps(manifest,indent=2))
