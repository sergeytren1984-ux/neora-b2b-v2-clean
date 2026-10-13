"""Paired historical macro-context diagnostic with honest source definitions.

Latest-vintage FRED history is not a proven historical receipt stream. Broad
USD and Nasdaq cash close are NOT relabelled DXY or Nasdaq futures. This data
cannot independently satisfy full-system admission or required live factors.
"""
import argparse,csv,datetime as dt,json,pathlib
import numpy as np
import forecast as f

SERIES={'DGS10':{'lag_days':2,'name':'Treasury constant maturity 10y daily yield','yield':True},
    'DTWEXBGS':{'lag_days':10,'name':'Nominal broad USD index, not DXY','yield':False},
    'NASDAQ100':{'lag_days':2,'name':'Nasdaq100 cash close, not futures','yield':False}}

def read_series(path):
    rows=[]
    with pathlib.Path(path).open() as stream:
        for r in csv.DictReader(stream):
            date=r.get('observation_date',r.get('DATE'));value=list(r.values())[1]
            if value in ('.',''):continue
            n=float(value)
            if not np.isfinite(n) or n<=0:raise ValueError('invalid macro level')
            rows.append((int(dt.datetime.fromisoformat(date).replace(tzinfo=dt.timezone.utc).timestamp()*1000),n))
    a=np.array(rows)
    if len(a)<30 or np.any(np.diff(a[:,0])<=0):raise ValueError('macro dates invalid')
    return a

def row(series,anchor):
    values=[]
    for name,s in series.items():
        rule=SERIES[name];cut=anchor-rule['lag_days']*86400000
        i=np.searchsorted(s[:,0],cut,side='right')-1
        if i<20 or anchor-s[i,0]>21*86400000:return None
        now=s[i,1]
        changes=[now-s[i-lag,1] if rule['yield'] else np.log(now/s[i-lag,1]) for lag in (1,5,20)]
        values.extend(changes);values.append((anchor-s[i,0])/86400000)
    return values

def main(arrays,out):
    series={name:read_series('inputs/macro_price_history/'+name+'.csv') for name in SERIES}
    a=dict(np.load(arrays,allow_pickle=False));keep=[];extra=[];missing=[]
    for j,anchor in enumerate(a['anchors']):
        values=row(series,int(anchor))
        if values is None:missing.append(f.iso(anchor))
        else:keep.append(j);extra.append(values)
    d={k:v[keep] for k,v in a.items()};root=pathlib.Path(out);root.mkdir(exist_ok=True,parents=True)
    np.savez_compressed(root/'spot_paired.npz',**d)
    d['x']=np.c_[d['x'],np.array(extra)];np.savez_compressed(root/'with_macro.npz',**d)
    f.write(root/'provenance.json',{'schema':'macro-history-paired-diagnostic-v1','historical_only':True,
        'series':SERIES,'kept':len(keep),'missing_anchors':missing,'receipt_times_unverified':True,
        'fixed_lags_are_not_verified_publication_times':True,'latest_vintage_not_first_release':True,
        'not_DXY_or_Nasdaq_futures':True,'trading_authority':False,'full_system_ready':False})
    print('PAIRED_MACRO_CONTEXT',len(keep),'features',d['x'].shape[1],'excluded',len(missing),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--arrays',required=True);p.add_argument('--output',required=True);args=p.parse_args();main(args.arrays,args.output)
