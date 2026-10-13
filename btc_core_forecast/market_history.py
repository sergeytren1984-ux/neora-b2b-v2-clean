"""Causal spot history from checksum-verified archives and closed live candles."""
import concurrent.futures,csv,gzip,hashlib,io,json,pathlib,time,urllib.parse,urllib.request,zipfile
import numpy as np
import forecast as f

API='https://data-api.binance.vision/api/v3/klines'
BASE='https://data.binance.vision/data/spot/'

def fetch(url):
    with urllib.request.urlopen(url,timeout=40) as response:return response.read()

def archive(url,cache):
    dest=pathlib.Path(cache)/url.rsplit('/',1)[-1];dest.parent.mkdir(parents=True,exist_ok=True)
    data=dest.read_bytes() if dest.exists() else fetch(url)
    sha=hashlib.sha256(data).hexdigest();expected=fetch(url+'.CHECKSUM').decode().split()[0]
    if sha!=expected:raise ValueError('publisher checksum mismatch')
    dest.write_bytes(data)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names=[n for n in z.namelist() if n.endswith('.csv')]
        if len(names)!=1:raise ValueError('ambiguous archive')
        rows=list(csv.reader(io.StringIO(z.read(names[0]).decode())))
    for row in rows:
        for k in (0,6):
            value=int(row[k]);row[k]=value//1000 if value>=10**14 else value
    return rows,{'url':url,'sha256':sha,'rows':len(rows)}

def long_tail(anchor,cache,base_rows=None,frozen_archives=None):
    # Fixed archives end before the initial deployment. Later past candles are
    # retrieved now, never represented as contemporaneously collected earlier.
    urls=[BASE+'monthly/klines/BTCUSDT/5m/BTCUSDT-5m-2026-'+m+'.zip' for m in ('07','08','09')]
    urls += [BASE+f'daily/klines/BTCUSDT/5m/BTCUSDT-5m-2026-10-{day:02d}.zip' for day in range(1,12)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        parts=list(pool.map(lambda url:archive(url,cache),urls))
    provenance=[meta for _,meta in parts]
    if frozen_archives is not None and provenance!=frozen_archives:raise ValueError('frozen archive bytes changed')
    rows=[] if base_rows is None else list(base_rows)
    rows.extend(row for part,_ in parts for row in part if int(row[6])+1<=anchor)
    if not rows:raise ValueError('no spot history')
    cursor=int(rows[-1][6])+1
    while cursor<anchor:
        query=urllib.parse.urlencode({'symbol':'BTCUSDT','interval':'5m','startTime':cursor,'endTime':anchor-1,'limit':1000})
        raw=fetch(API+'?'+query);part=json.loads(raw)
        part=[r for r in part if cursor<=int(r[0]) and int(r[6])+1<=anchor]
        if not part or int(part[0][0])!=cursor:raise ValueError('missing live bridge candle')
        rows.extend(part);cursor=int(rows[-1][6])+1
    # Validates continuity, dimensions, OHLC and taker constraints through reader.
    path=pathlib.Path(cache)/'assembled.json.gz';path.write_bytes(gzip.compress(json.dumps(rows,separators=(',',':')).encode(),mtime=0))
    t,a=f.read(path,anchor)
    if int(t[-1])!=anchor:raise ValueError('stale last closed spot candle')
    return t,a,provenance,hashlib.sha256(path.read_bytes()).hexdigest()

if __name__=='__main__':
    anchor=int(time.time()*1000)//300000*300000
    t,a,provenance,sha=long_tail(anchor,'inputs/deployment_archives')
    f.write('inputs/deployment_tail_provenance.json',{'anchor':anchor,'archives':provenance,'sha256':sha})
    print('CAUSAL_SPOT_TAIL',f.iso(t[0]),f.iso(t[-1]),len(a),flush=True)
