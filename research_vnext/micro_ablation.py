"""Fixed 5m/15m ablation on the same hourly forecast anchors and future labels."""
import gzip
import hashlib
import json
from pathlib import Path

import numpy as np

from benchmark import (read_history, features, first_touch, masks, fit_candidates,
                       metrics, block_ci)

DATA=Path('research_vnext/data')

def load(interval):
    path=DATA/f'BTCUSDT_{interval}_2024-01_2026-06.json.gz'
    rows=json.loads(gzip.decompress(path.read_bytes()))
    t=np.asarray([int(r[0]) for r in rows],dtype=np.int64)
    c=np.asarray([float(r[4]) for r in rows]);v=np.asarray([float(r[5]) for r in rows])
    trades=np.asarray([float(r[8]) for r in rows]);taker=np.asarray([float(r[9]) for r in rows])
    return t,c,v,trades,taker,hashlib.sha256(path.read_bytes()).hexdigest()

def micro_features(anchors,interval):
    t,c,v,trades,taker,digest=load(interval)
    duration={'5m':300000,'15m':900000}[interval]
    # anchor is the close time of the source 1h candle; all rows must close by it.
    last_open=anchors-duration
    pos=np.searchsorted(t,last_open)
    if np.any(pos>=len(t)) or np.any(t[pos]!=last_open) or np.any(pos<289):
        raise ValueError('5m/15m closed-candle alignment failed')
    z=np.log(c)
    result=[]
    for j in pos:
        returns=[z[j]-z[j-k] for k in (1,3,12,48) if k*duration<=4*3600000]
        recent=np.diff(z[j-12:j+1]);previous=np.diff(z[j-24:j-11])
        result.append(returns+[
            float(np.mean(recent)-np.mean(previous)),
            float(np.mean(abs(recent))),
            float(np.log((np.mean(v[j-11:j+1])+1)/(np.mean(v[j-143:j+1])+1))),
            float(np.log((np.mean(trades[j-11:j+1])+1)/(np.mean(trades[j-143:j+1])+1))),
            float(np.mean(taker[j-11:j+1]/np.maximum(v[j-11:j+1],1e-12))),
            float(np.mean(taker[j-2:j+1]/np.maximum(v[j-2:j+1],1e-12)) -
                  np.mean(taker[j-11:j-2]/np.maximum(v[j-11:j-2],1e-12)))])
    X=np.asarray(result)
    if not np.all(np.isfinite(X)):raise ValueError('Nonfinite micro features')
    return X,digest

def run(history):
    t,hi,lo,c,v,trades,taker,source=read_history(history)
    ix,dates,spot,hourly,gate=features(t,hi,lo,c,v,trades,taker)
    eligible=dates<np.datetime64('2026-07-01T00:00')
    ix=ix[eligible];dates=dates[eligible];spot=spot[eligible];hourly=hourly[eligible];gate=gate[eligible]
    anchors=t[ix]+3600000
    x5,sha5=micro_features(anchors,'5m');x15,sha15=micro_features(anchors,'15m')
    y,when=first_touch(ix,hi,lo,c,.01,24)
    folds=(
       ('2025Q3','2025-04-01','2025-04-01','2025-07-01','2025-07-08','2025-10-01'),
       ('2025Q4','2025-07-01','2025-07-01','2025-10-01','2025-10-08','2026-01-01'),
       ('2026H1','2025-10-01','2025-10-01','2026-01-01','2026-01-08','2026-07-01'))
    families={'spot':spot,'spot_hourly':np.column_stack((spot,hourly)),
              'plus_5m':np.column_stack((spot,hourly,x5)),
              'plus_5m_15m':np.column_stack((spot,hourly,x5,x15))}
    output={'schema':'btc-microstructure-ablation-research','target':'±1pct_24h',
            'classes':['LOWER_FIRST','UPPER_FIRST','NEITHER','AMBIGUOUS_SAME_BAR'],
            'history_sha256':source,'micro_5m_sha256':sha5,'micro_15m_sha256':sha15,
            'forecast_authority':False,'folds':{}}
    for label,*bounds in folds:
        tr,ca,te=masks(dates,24,*map(np.datetime64,bounds))
        baseline=None;fold={'n':int(sum(te)),'families':{}}
        for family,X in families.items():
            candidates=fit_candidates(X,gate,y,tr,ca,te,when,24)
            if baseline is None:baseline=candidates['frequency']
            fold['families'][family]={k:{'scores':metrics(p,y[te]),
                'brier_gain_vs_frequency_ci':block_ci(baseline,p,y[te],dates[te]),
                'brier_gain_vs_logistic_same_family_ci':block_ci(candidates['logistic'],p,y[te],dates[te])}
                for k,p in candidates.items()}
        output['folds'][label]=fold
    return output

if __name__=='__main__':
    out=run('btc_1h_2024_to_sep24_2026.json')
    Path('research_vnext/micro_result.json').write_text(json.dumps(out,indent=2,sort_keys=True)+'\n')
    print('saved research_vnext/micro_result.json')
