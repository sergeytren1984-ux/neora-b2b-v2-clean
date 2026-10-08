"""Recreate the exact public 1h source used by this benchmark."""
import concurrent.futures
import datetime as dt
import hashlib
import json
import urllib.request
from pathlib import Path

EXPECTED_SHA='3e78a339e60fec957dea2c0884c6840d66a92351ac04b4198623f1da10165fc9'
END=int(dt.datetime(2026,9,25,tzinfo=dt.timezone.utc).timestamp()*1000)-1
START=int(dt.datetime(2024,1,1,tzinfo=dt.timezone.utc).timestamp()*1000)

def fetch(index):
    end=END-index*1000*3600000
    url=f'https://data-api.binance.vision/api/v3/klines?symbol=BTCUSDT&interval=1h&limit=1000&endTime={end}'
    with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'btc-predictive-research'}),timeout=40) as f:
        return json.load(f)

if __name__=='__main__':
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        chunks=list(pool.map(fetch,range(25)))
    indexed={int(row[0]):row for chunk in chunks for row in chunk if START<=int(row[0])<END}
    rows=[indexed[k] for k in sorted(indexed)]
    blob=json.dumps(rows,separators=(',',':')).encode()
    digest=hashlib.sha256(blob).hexdigest()
    if len(rows)!=23952 or digest!=EXPECTED_SHA:
        raise ValueError(f'Historical source changed: rows={len(rows)} sha256={digest}')
    Path('btc_1h_2024_to_sep24_2026.json').write_bytes(blob)
    print('BTC 1h source verified',digest)
