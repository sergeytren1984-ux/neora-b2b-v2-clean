"""Fixed historical multi-period benchmark. No prospective or trading claims."""
from __future__ import annotations
import argparse,hashlib,json,pathlib
import numpy as np
import forecast as f

FOLDS=(('2025-07-01T00:00:00Z','2025-10-01T00:00:00Z'),
       ('2025-10-01T00:00:00Z','2026-01-01T00:00:00Z'),
       ('2026-01-01T00:00:00Z','2026-04-01T00:00:00Z'),
       ('2026-04-01T00:00:00Z','2026-07-01T00:00:00Z'))
HORIZONS=(1,4,24)
MAX_SCENARIOS=240
SEED=60113

def split(anchors,start,end):
    start=f.stamp(start);end=f.stamp(end);label_end=anchors+72*3600000
    calstart=start-60*86400000
    train=np.flatnonzero((anchors>=calstart-365*86400000)&(label_end<calstart))
    cal=np.flatnonzero((anchors>=calstart)&(label_end<start))
    test=np.flatnonzero((anchors>=start)&(anchors<end)&(label_end<end))
    if min(len(train),len(cal),len(test))<240:raise ValueError('insufficient purged fold')
    if label_end[train].max()>=anchors[cal].min() or label_end[cal].max()>=anchors[test].min():
        raise ValueError('chronology leakage')
    return train,cal,test

def estimate(x,c,h,l,scales,tr,ca):
    mu,sd,coef=f.fit(x[tr],c[tr]);model={'mu':mu,'sd':sd,'coef':coef}
    # Calibration trajectories all have complete outcome BEFORE the next period.
    loc=f.predict(model,x[ca])
    for k,y in (('close',c),('high',h),('low',l)):
        model['res_'+k]=y[ca]-loc;model['base_'+k]=y[ca]
    # Fixed deterministic subsampling gives equal-size path distributions.
    choose=np.linspace(0,len(ca)-1,min(MAX_SCENARIOS,len(ca)),dtype=int)
    for k in list(model):
        if k.startswith(('res_','base_')):model[k]=model[k][choose]
    model['cal_scales']=scales[ca][choose]
    return model

def distribution(model,x,sigma,kind):
    if kind=='ridge':return f.paths(model,x,sigma)
    if kind=='volatility':return f.paths(model,x,sigma,True)
    if kind=='fixed_empirical':return tuple(model['base_'+k]*model['cal_scales'][:,None] for k in ('close','high','low'))
    raise ValueError('unknown benchmark')

def endpoint_classes(samples,h):
    b={1:.007,4:.012,24:.02}[h]
    s=samples[:,h-1]
    return np.where(s>=np.log1p(b),0,np.where(s<=np.log1p(-b),1,2))

def score_fold(model,x,scales,c,h,l,spot,anchors,te):
    kinds=('ridge','volatility','fixed_empirical')
    store={k:{hours:[] for hours in HORIZONS} for k in kinds}
    barrier={k:[] for k in kinds};economic={k:[] for k in kinds};waited={k:0 for k in kinds};always=[]
    for j in te:
        actual=c[j]*scales[j]
        true_touch=int(f.first_passage(h[j:j+1]*scales[j],l[j:j+1]*scales[j])[0])
        yy4=np.eye(4)[true_touch]
        # Different actions execute at t+1h and t+25h, respectively.
        realized=147600/(spot[j]*np.exp(actual[24])+350)-147600/(spot[j]*np.exp(actual[0])+350)
        always.append(realized)
        for kind in kinds:
            paths,high,low=distribution(model,x[j],scales[j],kind)
            predclass=f.first_passage(high,low);pp=np.bincount(predclass,minlength=4)/len(predclass)
            barrier[kind].append(float(np.sum((pp-yy4)**2)))
            predgain=147600/(spot[j]*np.exp(paths[:,24])+350)-147600/(spot[j]*np.exp(paths[:,0])+350)
            # Predeclared research rule: mean gain positive and probability >60%.
            wait=predgain.mean()>0 and np.mean(predgain>0)>.60
            waited[kind]+=int(wait);economic[kind].append(float(realized if wait else 0))
            for hours in HORIZONS:
                s=spot[j]*np.exp(paths[:,hours-1]);truth=spot[j]*np.exp(actual[hours-1])
                q=np.quantile(s,[.1,.5,.9]);yy=int(endpoint_classes(actual[None,:],hours)[0])
                probs=np.bincount(endpoint_classes(paths,hours),minlength=3)/len(paths)
                row=[abs(q[1]-truth),f.crps(s,truth),float(q[0]<=truth<=q[2]),
                     float(np.sum((probs-np.eye(3)[yy])**2)),abs(spot[j]-truth),
                     q[2]-q[0],np.log(q[1]/spot[j]),truth,q[0],q[2]]
                store[kind][hours].append(row)
    result={};refanchors=anchors[te];always=np.array(always)
    for kind in kinds:
        result[kind]={'price':{},'barrier_brier':float(np.mean(barrier[kind])),
            'wait_24h':{'signals':waited[kind],'gain_vs_buy_now_btc':f.daily_stats(np.array(economic[kind]),refanchors),
                'gain_vs_always_wait_btc':f.daily_stats(np.array(economic[kind])-always,refanchors)}}
        for hours in HORIZONS:
            v=np.asarray(store[kind][hours]);base=np.asarray(store['volatility'][hours])
            # Interval score penalizes both misses and excessive width.
            interval_score=v[:,5]+10*np.maximum(v[:,8]-v[:,7],0)+10*np.maximum(v[:,7]-v[:,9],0)
            result[kind]['price'][str(hours)+'h']={'mae_usdt':float(v[:,0].mean()),'crps_usdt':float(v[:,1].mean()),
                'coverage_80pct':float(v[:,2].mean()),'endpoint_3class_brier':float(v[:,3].mean()),
                'mean_interval_width_usdt':float(v[:,5].mean()),'interval_score_80pct':float(interval_score.mean()),
                'mae_gain_vs_persistence':f.daily_stats(v[:,4]-v[:,0],refanchors),
                'crps_gain_vs_volatility':f.daily_stats(base[:,1]-v[:,1],refanchors),
                'direction_brier_gain_vs_volatility':f.daily_stats(base[:,3]-v[:,3],refanchors)}
    return result,store

def run(raw,out):
    out=pathlib.Path(out);out.mkdir(parents=True,exist_ok=True)
    t,a=f.read(raw);idx,x,scales,c,h,l=f.arrays(t,a);anchors=t[idx];spot=a[idx,4]
    np.savez_compressed(out/'causal_arrays.npz',idx=idx,x=x,scales=scales,close=c,high=h,low=l,anchors=anchors,spot=spot)
    report={'schema':'btc-core-fixed-walkforward-v2','historical_only':True,'history_previously_used_in_project':True,
        'trading_authority':False,'prospective_skill_proven':False,'R6_in_numeric_model':False,
        'raw_sha256':hashlib.sha256(pathlib.Path(raw).read_bytes()).hexdigest(),
        'code_sha256':hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest(),
        'raw_n':len(a),'hourly_n':len(idx),'folds':{},
        'preset':{'training_days':365,'calibration_days':60,'complete_label_embargo_hours':72,'scenario_n_max':240,
            'ridge':f.RIDGE,'wait_rule':'mean additional BTC >0 and probability of more BTC >0.60',
            'capital_assumption_usdt':147600,'premium_assumption_usdt_per_btc':350},
        'missing_factors':['verified historical R6 states','macro vintages','OTC quotes and rejected/partial execution'],
        'long_term_90_100k_validated':False}
    for start,end in FOLDS:
        tr,ca,te=split(anchors,start,end);model=estimate(x,c,h,l,scales,tr,ca)
        print('EVALUATING',start,len(tr),len(ca),len(te),flush=True)
        stats,rows=score_fold(model,x,scales,c,h,l,spot,anchors,te)
        label=start[:10]
        report['folds'][label]={'start':start,'end_exclusive':end,'train_n':len(tr),'calibration_n':len(ca),'test_n':len(te),
            'train_last_outcome':f.iso((anchors[tr]+72*3600000).max()),
            'calibration_last_outcome':f.iso((anchors[ca]+72*3600000).max()),'models':stats}
        for kind in rows:
            np.savez_compressed(out/('predictions_'+label+'_'+kind+'.npz'),anchors=anchors[te],
                **{str(hh)+'h':np.asarray(v) for hh,v in rows[kind].items()})
        f.write(out/'walkforward.json',report)
        print('FOLD_COMPLETE',label,json.dumps({k:{hh:round(v['mae_gain_vs_persistence']['среднее_улучшение'],2)
            for hh,v in m['price'].items()} for k,m in stats.items()}),flush=True)
    # Stability is diagnostic only; these criteria are not prospective admission.
    stable={}
    for kind in ('ridge','volatility','fixed_empirical'):
        gains={hh:[d['models'][kind]['price'][hh]['mae_gain_vs_persistence']['среднее_улучшение'] for d in report['folds'].values()] for hh in ('1h','4h','24h')}
        stable[kind]={'positive_mae_fold_count':{hh:sum(v>0 for v in g) for hh,g in gains.items()},
            'all_mae_horizons_positive_all_folds':all(all(v>0 for v in g) for g in gains.values()),
            'trading_authority':False}
    report['stability']=stable;f.write(out/'walkforward.json',report)
    print('HISTORICAL_RESEARCH_COMPLETE',json.dumps(stable),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--raw',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();run(a.raw,a.output)
