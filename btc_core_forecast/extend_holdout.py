"""Fetch July 2026 archive with publisher checksum; append causal July labels.

July is excluded from previous four-quarter diagnostics. Its historical status
and possible prior project usage are NOT represented as future evidence.
"""
import csv,gzip,hashlib,io,json,pathlib,urllib.request,zipfile
import numpy as np
import forecast as f
from add_regime import regime

URL='https://data.binance.vision/data/spot/monthly/klines/BTCUSDT/5m/BTCUSDT-5m-2026-07.zip'

def get(url):
    with urllib.request.urlopen(url,timeout=40) as response:return response.read()

def main():
    root=pathlib.Path('inputs');archive=root/'holdout_202607.zip'
    content=archive.read_bytes() if archive.exists() else get(URL)
    checksum=get(URL+'.CHECKSUM').decode().split()[0]
    actual=hashlib.sha256(content).hexdigest()
    if actual!=checksum:raise ValueError('publisher archive checksum mismatch')
    archive.write_bytes(content)
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        names=[n for n in z.namelist() if n.endswith('.csv')]
        if len(names)!=1:raise ValueError('ambiguous archive')
        more=list(csv.reader(io.StringIO(z.read(names[0]).decode())))
    for row in more:
        for k in (0,6):
            v=int(row[k]);row[k]=v//1000 if v>=10**14 else v
    with gzip.open(root/'spot_2024_2026H1.json.gz','rt') as stream:rows=json.load(stream)
    old_length=len(rows);rows.extend(more)
    combined=root/'spot_through_july2026.json.gz'
    combined.write_bytes(gzip.compress(json.dumps(rows,separators=(',',':')).encode(),mtime=0))
    t,a=f.read(combined)
    previous=dict(np.load('btc_core_forecast/long_results/regime_arrays_complete.npz',allow_pickle=False))
    indices=[i for i in range(int(previous['idx'][-1])+1,len(a)-72*12) if t[i]%3600000==0]
    if not indices:raise ValueError('no July complete labels')
    extra={k:[] for k in previous}
    for i in indices:
        x,s=f.feature(a,i,t[i]);extra['idx'].append(i);extra['anchors'].append(t[i]);extra['spot'].append(a[i,4]);extra['scales'].append(s)
        extra['x'].append(np.r_[x,regime(a,i)])
        extra['close'].append(np.log(a[i+np.arange(1,73)*12,4]/a[i,4])/s)
        extra['high'].append([np.log(a[i+(h-1)*12+1:i+h*12+1,2].max()/a[i,4])/s for h in range(1,73)])
        extra['low'].append([np.log(a[i+(h-1)*12+1:i+h*12+1,3].min()/a[i,4])/s for h in range(1,73)])
    output=pathlib.Path('btc_core_forecast/long_results/july_arrays.npz')
    np.savez_compressed(output,**{k:np.concatenate([v,np.asarray(extra[k])]) for k,v in previous.items()})
    if np.any(np.diff(np.concatenate([previous['anchors'],np.asarray(extra['anchors'])]))!=3600000):raise ValueError('hourly label grid gap')
    f.write('btc_core_forecast/long_results/july_provenance.json',{'url':URL,'publisher_sha256':checksum,'local_sha256':actual,
        'july_rows':len(more),'new_complete_hourly_labels':len(indices),'historical_only':True,
        'previous_project_usage_unknown':True,'never_claim_unseen_future_evidence':True})
    print('JULY_ARCHIVE_VERIFIED',len(more),'complete hourly labels',len(indices),flush=True)

if __name__=='__main__':main()
