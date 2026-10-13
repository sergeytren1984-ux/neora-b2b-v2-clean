"""Paired stronger-baseline checks, seven-day blocks, fixed extra July period.

Research only. Historical selection does not prove prospective or trading skill.
"""
import argparse,pathlib
import numpy as np
from scipy.signal import lfilter
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
import forecast as f
import walkforward as w
import conditional_path as c

KINDS=('vol24','vol1','vol4','ewma1','ewma4','har')

def block_stats(values,anchors):
    days=anchors//86400000;keys=np.unique(days)
    means=np.array([values[days==d].mean() for d in keys]);n=len(means)
    if n<14:return {'mean':float(np.mean(values)),'days':n,'ci95':None,'effective_week_blocks':n/7}
    blocks=np.array([means[i:i+7] for i in range(n-6)])
    rng=np.random.default_rng(60113)
    draw=blocks[rng.integers(len(blocks),size=(5000,int(np.ceil(n/7))))].reshape(5000,-1)[:,:n].mean(1)
    return {'mean':float(np.mean(values)),'days':n,'ci95':np.quantile(draw,[.025,.975]).tolist(),
        'effective_week_blocks':n/7,'independent_future_evidence':False}

def har_features(x,scales):
    # HAR-style volatility-only baseline, with separate absolute level.
    values=np.maximum(x[:,[1,5,9,13,22,25,28]],1e-8)
    return np.c_[np.log(values/scales[:,None]),np.log(scales)]

def ewma_from_raw(path,idx):
    _,a=f.read(path);returns=np.r_[0.,np.diff(np.log(a[:,4]))]
    result={}
    for name,half_life in (('ewma1',12),('ewma4',48)):
        decay=np.exp(-np.log(2)/half_life)
        result[name]=np.sqrt(np.maximum(lfilter([1-decay],[1,-decay],returns**2),1e-16))[idx]
    return result

def run(arrays,raw,out):
    a=dict(np.load(arrays,allow_pickle=False));out=pathlib.Path(out);out.mkdir(exist_ok=True,parents=True)
    ema=ewma_from_raw(raw,a['idx']);harx=har_features(a['x'],a['scales'])
    targets=c.volatility_targets(a['close']);folds=w.FOLDS+(('2026-07-01T00:00:00Z','2026-08-01T00:00:00Z'),)
    result={'schema':'btc-strong-baseline-paired-check-v1','historical_only':True,'trading_authority':False,
        'parameters_changed_from_conditional_candidate':False,'bootstrap_block_days':7,
        'July_previous_project_use_unknown':True,'folds':{}}
    for start,end in folds:
        tr,ca,te=w.split(a['anchors'],start,end);m=c.fit(a['x'],a['close'],a['high'],a['low'],tr,ca)
        logs=np.column_stack([head.predict(a['x'][te]) for head in m['heads']])
        cc=ca[np.linspace(0,len(ca)-1,min(w.MAX_SCENARIOS,len(ca)),dtype=int)]
        har=[]
        for k in range(4):
            head=make_pipeline(StandardScaler(),Ridge(alpha=1.))
            head.fit(harx[tr],targets[tr,k]);har.append(head)
        harcal=np.column_stack([head.predict(harx[cc]) for head in har])
        hartest=np.column_stack([head.predict(harx[te]) for head in har])
        ratios={'vol24':np.ones(len(a['x'])),'vol1':a['x'][:,5]/a['scales'],
            'vol4':a['x'][:,9]/a['scales'],**{k:v/a['scales'] for k,v in ema.items()}}
        scores={kind:{hh:[] for hh in w.HORIZONS} for kind in KINDS}
        levels={hh:[] for hh in w.HORIZONS};coverage={hh:[] for hh in w.HORIZONS};candidate_scores={hh:[] for hh in w.HORIZONS}
        for row,j in enumerate(te):
            paths,_,_=c.distribution(m,a['x'][j],a['scales'][j],logs[row])
            basepaths={kind:m['close']*(ratios[kind][j]/np.maximum(ratios[kind][cc],1e-8))[:,None]*a['scales'][j]
                for kind in KINDS if kind!='har'}
            hm=dict(m,calibration_logs=harcal)
            basepaths['har']=c.distribution(hm,a['x'][j],a['scales'][j],hartest[row])[0]
            for hh in w.HORIZONS:
                spot=a['spot'][j];actual=spot*np.exp(a['close'][j,hh-1]*a['scales'][j]);pred=spot*np.exp(paths[:,hh-1])
                cs=f.crps(pred,actual);candidate_scores[hh].append(cs)
                lo,hi=np.quantile(pred,[.1,.9]);coverage[hh].append(float(lo<=actual<=hi));levels[hh].append(actual)
                for kind,bs in basepaths.items():scores[kind][hh].append(f.crps(spot*np.exp(bs[:,hh-1]),actual)-cs)
        fold={'coverage_80pct':{str(h):float(np.mean(v)) for h,v in coverage.items()},'comparisons':{}}
        aa=a['anchors'][te]
        for kind in KINDS:
            fold['comparisons'][kind]={str(h):block_stats(np.array(v),aa) for h,v in scores[kind].items()}
        result['folds'][start[:10]]=fold;f.write(out/'strong_baselines.json',result)
        np.savez_compressed(out/('paired_scores_'+start[:10]+'.npz'),anchors=aa,
            **{kind+'_'+str(h):np.array(v) for kind,hs in scores.items() for h,v in hs.items()},
            **{'candidate_crps_'+str(h):np.array(v) for h,v in candidate_scores.items()})
        print('STRONG_BASELINES',start[:10],{kind:{h:round(v['mean'],3) for h,v in hs.items()} for kind,hs in fold['comparisons'].items()},flush=True)
    result['positive_lower_CI_every_period_against_every_baseline']={str(h):all(
        fold['comparisons'][kind][str(h)]['ci95'] is not None and fold['comparisons'][kind][str(h)]['ci95'][0]>0
        for fold in result['folds'].values() for kind in KINDS) for h in w.HORIZONS}
    f.write(out/'strong_baselines.json',result)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--arrays',required=True);p.add_argument('--raw',required=True);p.add_argument('--output',required=True)
    args=p.parse_args();run(args.arrays,args.raw,args.output)
