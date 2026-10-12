"""Research ablation of v7R6 direction GIVEN its own estimated event risk.

The spot v7R6 multinomial forecaster estimates q=P(up)+P(down). Keep q
EXACTLY IDENTICAL across all alternatives. Learn only P(up|event) from
chronologically prior UP_FIRST vs DOWN_FIRST episodes; apply shrinks chosen
on a separate previously matured validation week. This does not claim a
market edge until prospective signed observed outcomes prove it.
"""
from __future__ import annotations
import argparse,datetime as dt,gzip,hashlib,json,math,pathlib,statistics
from btc_skill_rebuild.research_competing_barriers_v7r6 import (
    fit,prob,labels,SHRINK,normalized,standardize,softmax)
from btc_skill_rebuild.research_execution_drift_v7r6 import examples,STEP
from btc_skill_rebuild.research_walkforward_barriers_v7r6 import FOLDS,UTC

# Predeclared signed-flow/momentum features; forbid retrospective selection.
DIRECTION_INPUT_INDICES=(0,1,2,5,6,7,8,11)
DIRECTION_INPUT_NAMES=('mom15m','mom1h','mom4h',
                       'signed_taker_5m','signed_taker_15m','signed_taker_1h',
                       'short_vs_long_taker_delta','volatility_1h')
EPOCHS=160
STEP_SIZE=0.12
L2=1.5


def logistic(t):
    if t>=0:
        z=math.exp(-t);return 1/(1+z)
    z=math.exp(t);return z/(1+z)


def train_direction(events):
    """Labels only first-touch UP/DOWN; class availability from matured TRAIN."""
    only=[(x,y) for _,x,y in events if y in (0,1)]
    if len(only)<90 or len({y for x,y in only})<2:
        raise ValueError('too few independently matured first-touch events')
    reduced=[tuple(x[j] for j in DIRECTION_INPUT_INDICES) for x,y in only]
    prior=(sum(y==0 for x,y in only)+1)/(len(only)+2)
    # TRAIN-standardized, regularized logistic only; no feature selection.
    pseudo=[(i,x,0) for i,x in enumerate(reduced)]
    m,s=standardize(pseudo)
    xnorm=[normalized(x,m,s) for x in reduced]
    weight=[math.log(prior/(1-prior))]+[0.]*len(reduced[0])
    n=len(xnorm)
    for epoch in range(EPOCHS):
        grad=[0.]*len(weight)
        for xx,(_,yy) in zip(xnorm,only):
            p=logistic(sum(a*b for a,b in zip(weight,xx)))
            error=p-(yy==0)
            for j,v in enumerate(xx):grad[j]+=error*v
        lr=STEP_SIZE*(1-.5*epoch/EPOCHS)
        for j in range(len(weight)):
            pen=0. if j==0 else L2*weight[j]
            weight[j]-=lr*(grad[j]+pen)/n
    return {'mean':m,'scale':s,'coef':weight,'prior_UP_conditional':prior,
            'n_matured_training_events':len(only)}


def direction_up(m,x,shrink):
    reduced=[x[j] for j in DIRECTION_INPUT_INDICES]
    z=normalized(reduced,m['mean'],m['scale'])
    raw=logistic(sum(v*w for v,w in zip(m['coef'],z)))
    return (1-shrink)*m['prior_UP_conditional']+shrink*raw


def adjusted(spot_model,dir_model,x,spot_shrink,dir_shrink):
    p=prob(spot_model,x,spot_shrink)
    any_event=p[0]+p[1]
    share=direction_up(dir_model,x,dir_shrink)
    res=[any_event*share,any_event*(1-share),p[2],p[3]]
    if abs(sum(res)-1)>1e-9 or any(x<0 or not math.isfinite(x) for x in res):
        raise ValueError('conditional direction invalid normalized probabilities')
    return p,res


def event_score(p,y):return sum((v-(j==y))**2 for j,v in enumerate(p))/4


def score(data,spot_model,dir_model,spot_shrink,dir_shrink):
    improvements=[];event_only=[];byday={};warnings=0
    for at,x,y in data:
        prior,new=adjusted(spot_model,dir_model,x,spot_shrink,dir_shrink)
        # Compare two policies having the SAME event risk, only direction differs.
        delta=event_score(prior,y)-event_score(new,y)
        improvements.append(delta)
        if y in (0,1):event_only.append(delta)
        day=dt.datetime.fromtimestamp(at/1000,UTC).date().isoformat()
        byday.setdefault(day,[]).append(delta)
    daily=[statistics.mean(v) for v in byday.values()]
    return {'n_rows':len(data),'n_actual_first_touch_updown':len(event_only),
            'matched_any_event_risk':True,
            'brier_directional_gain_over_unmodified_spot':statistics.mean(improvements),
            'brier_directional_gain_conditioned_on_real_event':statistics.mean(event_only) if event_only else None,
            'n_days':len(daily),'positive_direction_days':sum(z>0 for z in daily),
            'day_block_L95_descriptive':statistics.mean(daily)-1.96*statistics.stdev(daily)/math.sqrt(len(daily)) if len(daily)>1 else None}


def run(raw_file,out):
    with gzip.open(raw_file,'rt') as f:rows=json.load(f)
    base=examples(rows);heads={}
    for head,(horizon,barrier) in {'1h':(12,.007),'4h':(48,.012)}.items():
        data=[]
        for i,at,x,close,logs in base:
            if i+horizon>=len(rows) or at%(15*60000):continue
            maturity=int(rows[i+horizon][0])+STEP
            y,t=labels(rows,i,horizon,barrier)
            data.append((at,maturity,x,y))
        folds=[]
        for fold in FOLDS:
            t=int(fold.timestamp()*1000);valstart=t-8*86400000;valend=t-86400000
            end=t+7*86400000
            tr=[(at,x,y) for at,due,x,y in data if due<valstart]
            va=[(at,x,y) for at,due,x,y in data if valstart<=at and due<valend]
            te=[(at,x,y) for at,due,x,y in data if t<=at<end]
            if min(map(len,(tr,va,te)))<300:raise ValueError('not enough matured feature windows')
            spot=fit(tr)
            # Match the previous v7R6 model selection procedure exactly:
            # select shrink against a TRAIN class-prior only on VALIDATION.
            def prior_score(s):
                q=spot[3]
                return statistics.mean(event_score(q,y)-event_score(prob(spot,x,s),y)
                       for at,x,y in va)
            spot_shrink=max(SHRINK,key=prior_score)
            dm=train_direction(tr)
            direction_shrink=max(SHRINK,key=lambda a:score(va,spot,dm,spot_shrink,a)['brier_directional_gain_over_unmodified_spot'])
            baseline=score(te,spot,dm,spot_shrink,0.)
            selected=score(te,spot,dm,spot_shrink,direction_shrink)
            # Separate prior-only conditional baseline from native spot policy.
            folds.append({'test_week_start':fold.isoformat(),
                'n_train':len(tr),'n_val':len(va),'n_test':len(te),
                'spot_shrink_selected_val':spot_shrink,
                'conditional_direction_shrink_selected_val':direction_shrink,
                'prior_conditional_up':dm['prior_UP_conditional'],
                'real_first_touch_events_used_for_training':dm['n_matured_training_events'],
                'validation':score(va,spot,dm,spot_shrink,direction_shrink),
                'known_historical_test':selected,
                'test_train_prior_conditional_direction':baseline})
            print('DIRECTION_CONDITIONED',head,str(fold.date()),'shrink',direction_shrink,
                  'delta_brier_vs_original',round(selected['brier_directional_gain_over_unmodified_spot'],7),
                  'events',selected['n_actual_first_touch_updown'],flush=True)
        heads[head]={'folds':folds,'positive_directed_folds':sum(
            f['known_historical_test']['brier_directional_gain_over_unmodified_spot']>0
            for f in folds)}
    result={'schema':'btc-v7r6-conditional-direction-ablation-math-v1',
      'data_gzip_sha256':hashlib.sha256(pathlib.Path(raw_file).read_bytes()).hexdigest(),
      'original_v7r6_event_risk_same_for_comparator_and_challenger':True,
      'direction_features_fixed_before_fold':DIRECTION_INPUT_NAMES,
      'historic_data_already_seen':True,'no_public_warning_generated':True,
      'trading_authority':False,'heads':heads}
    pathlib.Path(out).write_text(json.dumps(result,sort_keys=True,indent=2,allow_nan=False)+'\n')
    print('DIRECTION_CONDITIONAL_FOLDS',[(h,v['positive_directed_folds']) for h,v in heads.items()],flush=True)
    return result

if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('--raw',required=True);a.add_argument('--out',required=True)
    v=a.parse_args();run(v.raw,v.out)
