"""Aggregate paired historical evidence without declaring full-system readiness."""
import json,pathlib
import numpy as np
import forecast as f

def main():
    roots=[pathlib.Path('btc_core_forecast/robust_results')]*4+[pathlib.Path('btc_core_forecast/robust_july_complete')]
    labels=['2025-07-01','2025-10-01','2026-01-01','2026-04-01','2026-07-01']
    parts=[dict(np.load(root/('paired_scores_'+label+'.npz'),allow_pickle=False)) for root,label in zip(roots,labels)]
    result={'schema':'btc-component-stratified-historical-evidence-v1','scope':'distribution component only',
        'historical_only':True,'post_selection_diagnostic':True,'full_system_ready':False,
        'prospective_skill_proven':False,'trading_authority':False,'bootstrap_block_days':7,'comparisons':{}}
    for kind in ('vol24','vol1','vol4','ewma1','ewma4','har'):
        result['comparisons'][kind]={}
        for horizon in (1,4,24):
            arrays=[];blocks=[];weights=[]
            for part in parts:
                v=part[kind+'_'+str(horizon)];days=part['anchors']//86400000;unique=np.unique(days)
                daily=np.array([v[days==d].mean() for d in unique]);arrays.append(v);weights.append(len(v))
                blocks.append(np.array([daily[j:j+7] for j in range(len(daily)-6)]))
            rng=np.random.default_rng(60113);replicas=[]
            for part,b in zip(parts,blocks):
                n=len(np.unique(part['anchors']//86400000));replicas.append(b[rng.integers(len(b),size=(5000,int(np.ceil(n/7))))].reshape(5000,-1)[:,:n].mean(1))
            average=np.average(np.array(replicas),axis=0,weights=weights)
            ci=np.quantile(average,[.025,.975]).tolist();value=float(np.concatenate(arrays).mean())
            result['comparisons'][kind][str(horizon)]={'mean_crps_gain_usdt':value,'diagnostic_ci95':ci,
                'paired_observations':sum(weights),'period_means':[float(v.mean()) for v in arrays],
                'every_period_mean_positive':all(v.mean()>0 for v in arrays),
                'single_period_significance_not_implied':True,'historical_selection_bias_not_removed':True}
    f.write('btc_core_forecast/robust_results/component_evidence.json',result)
    print('HISTORICAL_COMPONENT_EVIDENCE', {k:v['1']['diagnostic_ci95'] for k,v in result['comparisons'].items()},flush=True)

if __name__=='__main__':main()
