"""Historical scaled-distance analogues of the two registered entry questions.

Absolute USD barriers are only used for the current operational mapping; their
ratios to the frozen 2026-10-03 reference close define historical tasks.
"""
import json
from pathlib import Path
import numpy as np

from benchmark import read_history,features,masks,fit_candidates,metrics,block_ci
from micro_ablation import micro_features
from derivatives_ablation import derivatives

REFERENCE=84672.01
SCENARIOS=(("entry_72h",82500,87000,72),("entry_7d",81500,88000,168),
           ("symmetric_2pct_72h",REFERENCE*.98,REFERENCE*1.02,72),
           ("symmetric_2pct_7d",REFERENCE*.98,REFERENCE*1.02,168))
FOLDS=(
       ('2025Q3','2025-04-01','2025-04-01','2025-07-01','2025-07-08','2025-10-01'),
       ('2025Q4','2025-07-01','2025-07-01','2025-10-01','2025-10-08','2026-01-01'),
       ('2026H1','2025-10-01','2025-10-01','2026-01-01','2026-01-08','2026-07-01'))

def labels(ix,hi,lo,c,lower_ratio,upper_ratio,h):
    y=np.full(len(ix),2,dtype=np.int8)
    when=np.full(len(ix),h+1,dtype=np.int16)
    lower=c[ix]*lower_ratio;upper=c[ix]*upper_ratio
    for step in range(1,h+1):
        active=when>h;dn=lo[ix+step]<=lower;up=hi[ix+step]>=upper
        hit=active&(dn|up)
        y[hit]=np.where(dn[hit]&up[hit],3,np.where(dn[hit],0,1))
        when[hit]=step
    return y,when

def run(history):
    t,hi,lo,c,v,trades,taker,source=read_history(history)
    ix,dates,spot,hourly,gate=features(t,hi,lo,c,v,trades,taker)
    keep=dates<np.datetime64('2026-07-01')
    ix=ix[keep];dates=dates[keep];spot=spot[keep];hourly=hourly[keep];gate=gate[keep]
    anchors=t[ix]+3600000
    x5,sha5=micro_features(anchors,'5m');x15,sha15=micro_features(anchors,'15m')
    deriv,valid,provenance=derivatives(anchors,spot,hourly)
    ix=ix[valid];dates=dates[valid];spot=spot[valid];hourly=hourly[valid];gate=gate[valid]
    x5=x5[valid];x15=x15[valid];deriv=deriv[valid]
    family={'hourly':np.column_stack((spot,hourly)),
            'hourly_micro':np.column_stack((spot,hourly,x5,x15)),
            'hourly_derivatives':np.column_stack((spot,hourly,deriv))}
    out={'schema':'btc-first-passage-operational-research','history_sha256':source,
         'micro_5m_sha256':sha5,'micro_15m_sha256':sha15,'derivatives':provenance,
         'reference_price_usdt':REFERENCE,'research_only':True,'scenarios':{}}
    for name,low,high,h in SCENARIOS:
        y,when=labels(ix,hi,lo,c,low/REFERENCE,high/REFERENCE,h)
        scenario={'lower_usdt':low,'upper_usdt':high,'horizon_hours':h,'folds':{}}
        for fold,*bounds in FOLDS:
            tr,ca,te=masks(dates,h,*map(np.datetime64,bounds))
            entry={'n':int(sum(te)),'counts':np.bincount(y[te],minlength=4).tolist(),'families':{}}
            for fname,X in family.items():
                p=fit_candidates(X,gate,y,tr,ca,te,when,h)
                entry['families'][fname]={m:{'scores':metrics(pp,y[te]),
                    'weekly_block_brier_gain_vs_frequency_ci':block_ci(p['frequency'],pp,y[te],dates[te]),
                    'weekly_block_brier_gain_vs_logistic_ci':block_ci(p['logistic'],pp,y[te],dates[te])}
                    for m,pp in p.items()}
            scenario['folds'][fold]=entry
        out['scenarios'][name]=scenario
    return out

if __name__=='__main__':
    out=run('btc_1h_2024_to_sep24_2026.json')
    Path('research_vnext/operational_result.json').write_text(json.dumps(out,indent=2,sort_keys=True)+'\n')
    print('saved research_vnext/operational_result.json')
