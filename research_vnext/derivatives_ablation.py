"""OI/funding ablation with conservative observed-timestamp lag and common anchors."""
import gzip
import hashlib
import json
from pathlib import Path

import numpy as np

from benchmark import read_history,features,first_touch,masks,fit_candidates,metrics,block_ci
from micro_ablation import micro_features

DATA=Path('research_vnext/data')

def derivatives(anchors, spot, hourly):
    oip=DATA/'BTCUSDT_oi_2024-01_2026-06.json.gz'
    fundp=DATA/'BTCUSDT_funding_2024-01_2026-06.json.gz'
    oi=sorted(json.load(gzip.open(oip,'rt')),key=lambda r:r['create_time'])
    ft=sorted(json.load(gzip.open(fundp,'rt')),key=lambda r:int(r['calc_time']))
    ot=np.asarray([np.datetime64(r['create_time'].replace(' ','T'),'ms').astype('int64') for r in oi])
    ov=np.asarray([float(r['sum_open_interest']) for r in oi])
    fv=np.asarray([float(r['last_funding_rate']) for r in ft])
    ftime=np.asarray([int(r['calc_time']) for r in ft])
    if np.any(np.diff(ot)<=0) or np.any(np.diff(ftime)<=0):raise ValueError('Duplicate/unsorted derivative timestamps')
    # Metric create_time is not proven publication time. Take only observations
    # timestamped >=1h earlier; reject missing history rather than interpolate.
    oidx=[np.searchsorted(ot,anchors-k*3600000,side='right')-1 for k in (1,2,5,25)]
    valid=np.ones(len(anchors),dtype=bool)
    for idx,k in zip(oidx,(1,2,5,25)):
        valid &= (idx>=0)
        valid &= (anchors-k*3600000-ot[np.maximum(idx,0)]<=600000)
        valid &= ov[np.maximum(idx,0)]>0
    fi=np.searchsorted(ftime,anchors-3600000,side='right')-1
    valid &= (fi>=1)
    valid &= (anchors-3600000-ftime[np.maximum(fi,0)]<=9*3600000)
    valid &= (anchors-3600000-ftime[np.maximum(fi-1,0)]<=17*3600000)
    ids=[np.maximum(x,0) for x in oidx]
    safe=lambda index:np.maximum(ov[index],1e-12)
    d1=np.log(safe(ids[0])/safe(ids[1]))
    d4=np.log(safe(ids[0])/safe(ids[2]))
    d24=np.log(safe(ids[0])/safe(ids[3]))
    funding=fv[np.maximum(fi,0)];fund_change=funding-fv[np.maximum(fi-1,0)]
    X=np.column_stack((d1,d4,d24,d1-d4/4,funding,fund_change,
                       spot[:,1]*d4,spot[:,3]*d24,hourly[:,0]*d4,
                       funding*d4))
    return X,valid,{"oi_sha256":hashlib.sha256(oip.read_bytes()).hexdigest(),
                     "funding_sha256":hashlib.sha256(fundp.read_bytes()).hexdigest(),
                     "timestamp_lag_hours":1,"publication_time_verified":False}

def run(history):
    t,hi,lo,c,v,trades,taker,source=read_history(history)
    ix,dates,spot,hourly,gate=features(t,hi,lo,c,v,trades,taker)
    keep=dates<np.datetime64('2026-07-01T00:00')
    ix=ix[keep];dates=dates[keep];spot=spot[keep];hourly=hourly[keep];gate=gate[keep]
    anchors=t[ix]+3600000
    x5,sha5=micro_features(anchors,'5m');x15,sha15=micro_features(anchors,'15m')
    deriv,valid,provenance=derivatives(anchors,spot,hourly)
    ix=ix[valid];dates=dates[valid];spot=spot[valid];hourly=hourly[valid]
    gate=gate[valid];x5=x5[valid];x15=x15[valid];deriv=deriv[valid]
    y,when=first_touch(ix,hi,lo,c,.01,24)
    families={'spot_hourly':np.column_stack((spot,hourly)),
              'plus_derivatives':np.column_stack((spot,hourly,deriv)),
              'plus_micro':np.column_stack((spot,hourly,x5,x15)),
              'plus_micro_derivatives':np.column_stack((spot,hourly,x5,x15,deriv))}
    folds=(
       ('2025Q3','2025-04-01','2025-04-01','2025-07-01','2025-07-08','2025-10-01'),
       ('2025Q4','2025-07-01','2025-07-01','2025-10-01','2025-10-08','2026-01-01'),
       ('2026H1','2025-10-01','2025-10-01','2026-01-01','2026-01-08','2026-07-01'))
    output={'schema':'btc-derivatives-ablation-research','target':'±1pct_24h',
            'history_sha256':source,'micro_5m_sha256':sha5,'micro_15m_sha256':sha15,
            'provenance':provenance,'anchors_dropped_for_missing_derivatives':int(sum(~valid)),
            'forecast_authority':False,'folds':{}}
    for label,*bounds in folds:
        tr,ca,te=masks(dates,24,*map(np.datetime64,bounds))
        baseline=None;fold={'n':int(sum(te)),'families':{}};paired={}
        for family,X in families.items():
            candidates=fit_candidates(X,gate,y,tr,ca,te,when,24)
            paired[family]=candidates['gbdt']
            if baseline is None:baseline=candidates['frequency']
            fold['families'][family]={k:{'scores':metrics(p,y[te]),
               'brier_gain_vs_frequency_ci':block_ci(baseline,p,y[te],dates[te]),
               'brier_gain_vs_logistic_same_family_ci':block_ci(candidates['logistic'],p,y[te],dates[te])}
               for k,p in candidates.items()}
        fold['gbdt_ablation_gain_ci']={family:block_ci(paired['spot_hourly'],p,y[te],dates[te])
                                        for family,p in paired.items() if family!='spot_hourly'}
        output['folds'][label]=fold
    return output

if __name__=='__main__':
    out=run('btc_1h_2024_to_sep24_2026.json')
    Path('research_vnext/derivatives_result.json').write_text(json.dumps(out,indent=2,sort_keys=True)+'\n')
    print('saved research_vnext/derivatives_result.json')
