"""One coherent conditional path candidate for price, direction and entry utility.

Fixed analogue weighting, no test-time parameter selection. This specification
is research only until its full admission criteria are independently met.
"""
import argparse,pathlib
import numpy as np
from sklearn.neighbors import NearestNeighbors
import forecast as f
import conditional_path as cp
import walkforward as w
from robust_distribution_check import block_stats

NEIGHBORS=256
LOCAL_WEIGHT=.5

def weighted_quantile(values,weights,quantiles):
    order=np.argsort(values);v=np.asarray(values)[order];p=np.asarray(weights)[order]
    if not np.isfinite(v).all() or not np.isfinite(p).all() or np.any(p<0) or p.sum()<=0:raise ValueError('invalid weighted distribution')
    p=p/p.sum();return np.interp(quantiles,np.cumsum(p)-p/2,v)

def weighted_crps(values,weights,actual):
    order=np.argsort(values);v=np.asarray(values)[order];p=np.asarray(weights)[order]
    if not np.isfinite(v).all() or not np.isfinite(p).all() or np.any(p<0) or p.sum()<=0:raise ValueError('invalid weighted distribution')
    p=p/p.sum();return float(np.dot(p,np.abs(v-actual))-np.dot(p*v,2*np.cumsum(p)-p-1))

def fit(a,tr,ca):
    # Conditional uncertainty is the existing fixed, historically tested part.
    volatility=cp.fit(a['x'],a['close'],a['high'],a['low'],tr,ca)
    mu=a['x'][tr].mean(0);sd=np.maximum(a['x'][tr].std(0),1e-8)
    xx=np.clip((a['x'][tr]-mu)/sd,-6,6)
    nn=NearestNeighbors(n_neighbors=min(NEIGHBORS,len(tr)),algorithm='brute',n_jobs=1).fit(xx)
    trainlogs=np.column_stack([head.predict(a['x'][tr]) for head in volatility['heads']])
    return {'volatility':volatility,'mu':mu,'sd':sd,'neighbors':nn,'train_logs':trainlogs,
        **{'train_'+k:a[k][tr] for k in ('close','high','low')},'trading_authority':False}

def paths(model,x,sigma,logs=None):
    if not np.isfinite(x).all() or not np.isfinite(sigma) or sigma<=0:raise ValueError('invalid causal input')
    vm=model['volatility']
    if logs is None:logs=np.array([head.predict(x[None])[0] for head in vm['heads']])
    query=np.clip((x-model['mu'])/model['sd'],-6,6)[None]
    distances,positions=model['neighbors'].kneighbors(query);ii=positions[0];d=distances[0]
    # Fixed distance bandwidth derived from the current causal neighbour set.
    bandwidth=max(float(np.median(d)),1e-8)
    local=np.exp(-(d/bandwidth)**2);local=local/local.sum()*LOCAL_WEIGHT
    multipliers=cp.interpolate(np.clip(logs-model['train_logs'][ii],np.log(.05),np.log(20)))
    localpaths=cp.transform(*(model['train_'+k][ii] for k in ('close','high','low')),multipliers)
    calpaths=cp.distribution(vm,x,sigma,logs)
    output=tuple(np.concatenate([part*sigma,cal]) for part,cal in zip(localpaths,calpaths))
    weights=np.r_[local,np.full(len(calpaths[0]),(1-LOCAL_WEIGHT)/len(calpaths[0]))]
    return (*output,weights)

def entry(close,weights,spot,wait,budget=147600.,premium=350.,delay=1):
    if isinstance(delay,bool) or isinstance(wait,bool) or int(delay)!=delay or int(wait)!=wait:raise ValueError('integer execution hours required')
    if delay<1 or wait<1 or delay+wait>72:raise ValueError('invalid execution timing')
    if not np.isfinite([spot,budget,premium]).all() or spot<=0 or budget<=0 or premium<0:raise ValueError('invalid execution assumptions')
    if not np.isfinite(weights).all() or np.any(weights<0) or weights.sum()<=0:raise ValueError('invalid trajectory probability mass')
    weights=weights/weights.sum()
    gain=budget/(spot*np.exp(close[:,delay+wait-1])+premium)-budget/(spot*np.exp(close[:,delay-1])+premium)
    expected=float(np.dot(weights,gain));probability=float(weights[gain>0].sum())
    return {'expected_extra_btc':expected,'probability_extra_btc':probability,
        'research_wait_signal':expected>0 and probability>.60,'trading_authority':False,
        'actual_operator_quotes':False}

def run(array_file,out,policy='conservative',fit_fn=None,paths_fn=None,candidate_spec=None):
    if policy not in ('conservative','expected-btc'):raise ValueError('unknown fixed decision policy')
    a=dict(np.load(array_file,allow_pickle=False));out=pathlib.Path(out);out.mkdir(exist_ok=True,parents=True)
    report={'schema':'btc-one-joint-direction-entry-candidate-v1','historical_only':True,'history_already_seen':True,
        'prospective_skill_proven':False,'trading_authority':False,'full_system_ready':False,
        'fixed_parameters':{'nearest_training_paths':NEIGHBORS,'local_probability_mass':LOCAL_WEIGHT,'wait_probability_threshold':.60},
        'R6_numeric_used':False,'macro_numeric_used':a['x'].shape[1]>30,'actual_OTC_used':False,
        'macro_history_availability_unverified':a['x'].shape[1]>30,
        'utility_is_per_hypothetical_decision_not_cumulative':True,'folds':{}}
    report['decision_policy']=policy
    if candidate_spec is not None:
        report['candidate_spec']=candidate_spec
        report['fixed_parameters']=candidate_spec
    report['admission_criteria_unchanged']=True
    report['expected_btc_policy_is_objective_not_calibrated_confidence_claim']=policy=='expected-btc'
    folds=w.FOLDS+(('2026-07-01T00:00:00Z','2026-08-01T00:00:00Z'),)
    for start,end in folds:
        tr,ca,te=w.split(a['anchors'],start,end);m=(fit if fit_fn is None else fit_fn)(a,tr,ca)
        logs=np.column_stack([head.predict(a['x'][te]) for head in m['volatility']['heads']])
        rows={h:[] for h in w.HORIZONS};gains={h:[] for h in w.HORIZONS};always={h:[] for h in w.HORIZONS};signals={h:0 for h in w.HORIZONS};touch=[]
        for row,j in enumerate(te):
            c,h,l,weights=(paths if paths_fn is None else paths_fn)(m,a['x'][j],a['scales'][j],logs[row]);spot=a['spot'][j];actual=a['close'][j]*a['scales'][j]
            bc,bh,bl=cp.distribution(m['volatility'],a['x'][j],a['scales'][j],logs[row])
            true_touch=f.first_passage(a['high'][j:j+1]*a['scales'][j],a['low'][j:j+1]*a['scales'][j])[0]
            pp=np.bincount(f.first_passage(h,l),weights=weights,minlength=4);bp=np.bincount(f.first_passage(bh,bl),minlength=4)/len(bc)
            touch.append(float(np.sum((bp-np.eye(4)[true_touch])**2)-np.sum((pp-np.eye(4)[true_touch])**2)))
            for horizon in w.HORIZONS:
                values=spot*np.exp(c[:,horizon-1]);truth=spot*np.exp(actual[horizon-1]);q=weighted_quantile(values,weights,[.1,.5,.9])
                pp=np.bincount(w.endpoint_classes(c,horizon),weights=weights,minlength=3);bp=np.bincount(w.endpoint_classes(bc,horizon),minlength=3)/len(bc)
                label=w.endpoint_classes(actual[None],horizon)[0]
                rows[horizon].append([abs(spot-truth)-abs(q[1]-truth),f.crps(spot*np.exp(bc[:,horizon-1]),truth)-weighted_crps(values,weights,truth),
                    np.sum((bp-np.eye(3)[label])**2)-np.sum((pp-np.eye(3)[label])**2),float(q[0]<=truth<=q[2]),
                    float((np.mean(bc[:,horizon-1]>0)-(actual[horizon-1]>0))**2-(np.sum(weights[c[:,horizon-1]>0])-(actual[horizon-1]>0))**2),
                    float(.25-(np.sum(weights[c[:,horizon-1]>0])-(actual[horizon-1]>0))**2),
                    float((np.mean(a['close'][ca,horizon-1]>0)-(actual[horizon-1]>0))**2-(np.sum(weights[c[:,horizon-1]>0])-(actual[horizon-1]>0))**2)])
                action=entry(c,weights,spot,horizon)
                waiting=action['research_wait_signal'] if policy=='conservative' else action['expected_extra_btc']>0
                signals[horizon]+=int(waiting)
                realized=147600/(spot*np.exp(actual[horizon])+350)-147600/(spot*np.exp(actual[0])+350)
                gains[horizon].append(realized if waiting else 0.);always[horizon].append(realized)
        fold={'price_direction':{},'entry':{},'barrier_brier_gain':block_stats(np.array(touch),a['anchors'][te])}
        for horizon in w.HORIZONS:
            z=np.array(rows[horizon]);anchors=a['anchors'][te]
            fold['price_direction'][str(horizon)]={'mae_gain_vs_persistence':block_stats(z[:,0],anchors),'crps_gain_vs_uncertainty_component':block_stats(z[:,1],anchors),
                    'direction_brier_gain':block_stats(z[:,2],anchors),'sign_brier_gain':block_stats(z[:,4],anchors),
                    'sign_brier_gain_vs_half':block_stats(z[:,5],anchors),'sign_brier_gain_vs_causal_calibration_prior':block_stats(z[:,6],anchors),
                    'coverage_80pct':float(z[:,3].mean())}
            chosen=np.array(gains[horizon]);fold['entry'][str(horizon)]={'signals':signals[horizon],
                'gain_vs_buy_now':block_stats(chosen,anchors),'gain_vs_always_wait':block_stats(chosen-np.array(always[horizon]),anchors)}
        report['folds'][start[:10]]=fold;f.write(out/'diagnostic.json',report)
        np.savez_compressed(out/('paired_'+start[:10]+'.npz'),anchors=a['anchors'][te],
            **{'price_direction_'+str(h):np.array(v) for h,v in rows.items()},
            **{'entry_gain_'+str(h):np.array(v) for h,v in gains.items()},
            **{'always_wait_gain_'+str(h):np.array(v) for h,v in always.items()})
        print('JOINT_CANDIDATE',start[:10],{h:round(v['mae_gain_vs_persistence']['mean'],3) for h,v in fold['price_direction'].items()},flush=True)
    report['stable_entry_gain_vs_both']=all(v['gain_vs_buy_now']['mean']>0 and v['gain_vs_always_wait']['mean']>0 for fold in report['folds'].values() for v in fold['entry'].values())
    f.write(out/'diagnostic.json',report)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--arrays',required=True);p.add_argument('--output',required=True)
    p.add_argument('--policy',choices=['conservative','expected-btc'],default='conservative')
    args=p.parse_args();run(args.arrays,args.output,args.policy)
