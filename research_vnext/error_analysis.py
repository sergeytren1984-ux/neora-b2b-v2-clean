"""Descriptive TP/FP/FN/TN samples; never used to tune this benchmark."""
import json
from pathlib import Path
import numpy as np
from benchmark import read_history,features,masks,fit_candidates
from operational_benchmark import labels,REFERENCE

FOLDS=(('2025Q4','2025-07-01','2025-07-01','2025-10-01','2025-10-08','2026-01-01'),
       ('2026H1','2025-10-01','2025-10-01','2026-01-01','2026-01-08','2026-07-01'))
SCENARIOS=(('entry_72h',82500,87000,72),('entry_7d',81500,88000,168))

def run(history):
    t,hi,lo,c,v,trades,taker,sha=read_history(history)
    ix,dates,spot,hourly,gate=features(t,hi,lo,c,v,trades,taker)
    X=np.column_stack((spot,hourly));out={'history_sha256':sha,'alert_rule':'calibrated_candidate_score_lower>0.5','cases':{}}
    for name,lower,upper,h in SCENARIOS:
        y,when=labels(ix,hi,lo,c,lower/REFERENCE,upper/REFERENCE,h)
        for fold,*bounds in FOLDS:
            tr,ca,te=masks(dates,h,*map(np.datetime64,bounds))
            p=fit_candidates(X,gate,y,tr,ca,te,when,h)['gbdt']
            actual=y[te]==0;pred=p[:,0]>.5
            index=np.flatnonzero(te)
            groups={'TP':np.flatnonzero(pred&actual),'FP':np.flatnonzero(pred&~actual),
                    'FN':np.flatnonzero(~pred&actual),'TN':np.flatnonzero(~pred&~actual)}
            sample={}
            for label,cases in groups.items():
                order=np.argsort(-p[cases,0] if label in ('TP','FP') else p[cases,0])
                sample[label]={'count':len(cases),'examples':[]}
                for j in cases[order[:3]]:
                    k=index[j]
                    sample[label]['examples'].append({'anchor_utc':str(dates[k]),
                        'close':round(float(c[ix[k]]),2),'observed_class':int(y[k]),
                        'calibrated_candidate_score_lower':round(float(p[j,0]),4),
                        'return_4h':round(float(spot[k,1]),5),
                        'return_24h':round(float(spot[k,3]),5),
                        'hourly_taker_buy_ratio_4h':round(float(hourly[k,0]),4)})
            out['cases'][name+'_'+fold]=sample
    return out

if __name__=='__main__':
    out=run('btc_1h_2024_to_sep24_2026.json')
    Path('research_vnext/error_result.json').write_text(json.dumps(out,indent=2,sort_keys=True)+'\n')
    print('saved research_vnext/error_result.json')
