"""Single v7R6 mathematical family: does causal recency weighting help
on actual nonoverlapping UTC decisions for 1h/4h first-touch outcomes?

No external events or tuning to October decline. Half-lives 7d/14d/full
history are frozen before validation; shrink selected on previous week.
Validation labels have matured before the target forward week. Historical
results are contaminated by previous research exposure (NOT prospective).
"""
from __future__ import annotations
import argparse,datetime as dt,gzip,json,hashlib,math,pathlib,statistics
from btc_skill_rebuild.research_execution_drift_v7r6 import examples,STEP
from btc_skill_rebuild.research_competing_barriers_v7r6 import (
  fit,standardize,normalized,softmax,prob,labels,SHRINK,EPOCHS,LEARNING_RATE,WEIGHT_DECAY)
from btc_skill_rebuild.research_walkforward_barriers_v7r6 import FOLDS,UTC
from btc_skill_rebuild.research_signal_information_v7r6 import brier,daily_gain,directional_loss

# 1h direction and risk must not use already closed future outcome.
HALF_LIVES_DAYS=(None,7,14)
HORIZONS={'1h':(12,.007),'4h':(48,.012)}

def weighted_fit(rows,days):
    if days is None:
        return fit([(t,x,y,None) for t,x,y in rows])
    if not 0<days<=30:raise ValueError('unregistered regime half-life')
    if len(rows)<1500:raise ValueError('not enough prior examples')
    cutoff=max(t for t,x,y in rows)
    means,scale=standardize([(t,x,y) for t,x,y in rows])
    xx=[normalized(x,means,scale) for t,x,y in rows]
    ys=[y for t,x,y in rows]
    raw_w=[math.exp(-math.log(2)*(cutoff-t)/(days*86400000)) for t,x,y in rows]
    total=sum(raw_w)
    weights=[w*len(rows)/total for w in raw_w]
    pri=[(sum(w for w,y in zip(weights,ys) if y==j)+1)/(len(rows)+4) for j in range(4)]
    k=len(xx[0]);n=len(xx)
    beta=[[0.]*k for i in range(4)]
    for j,p in enumerate(pri):beta[j][0]=math.log(p)
    for ep in range(EPOCHS):
        grad=[[0.]*k for i in range(4)]
        for features,y,w in zip(xx,ys,weights):
            p=softmax([sum(a*b for a,b in zip(features,beta[j])) for j in range(4)])
            for j in range(4):
                error=(p[j]-(j==y))*w
                for dim,v in enumerate(features):grad[j][dim]+=error*v
        rate=LEARNING_RATE*(1-.55*ep/EPOCHS)
        for j in range(4):
            for dim in range(k):
                pen=(WEIGHT_DECAY*beta[j][dim] if dim else 0.)
                beta[j][dim]-=rate*(grad[j][dim]+pen)/n
    return (means,scale,beta,pri)


def score(test,model,shrink):
    gain=[];dir_gain=[]
    prior=model[3]
    for t,x,y in test:
        p=prob(model,x,shrink)
        gain.append((t,brier(prior,y)-brier(p,y)))
        if y in (0,1):
            const=[(p[0]+p[1])*prior[0]/(prior[0]+prior[1]),
                   (p[0]+p[1])*prior[1]/(prior[0]+prior[1]),p[2],p[3]]
            dir_gain.append((t,brier(const,y)-brier(p,y)))
    return {'n_due':len(test),'n_directional_due':len(dir_gain),
         'brier_vs_own_train_prior':daily_gain(gain),
         'conditional_direction_gain_above_same_event_risk':daily_gain(dir_gain) if dir_gain else None}


def evaluate(rows):
    src=examples(rows)
    all_scores={}
    for head,(n,band) in HORIZONS.items():
        sample=[]
        for i,t,x,cl,lg in src:
            if t%(15*60000) or i+n>=len(rows):continue
            mature=int(rows[i+n][0])+STEP
            y,touch=labels(rows,i,n,band)
            sample.append((t,mature,x,y))
        folds=[]
        for start in FOLDS:
            t0=int(start.timestamp()*1000);end=t0+7*86400000
            val0=t0-8*86400000;valend=t0-86400000
            train=[(t,x,y) for t,mature,x,y in sample if mature<val0]
            valid=[(t,x,y) for t,mature,x,y in sample if val0<=t and mature<valend]
            test=[(t,x,y) for t,mature,x,y in sample if t0<=t<end and t%(n*STEP)==0]
            if min(len(train),len(valid),len(test))<40:raise ValueError('insufficient target samples')
            candidates=[]
            for d in HALF_LIVES_DAYS:
                model=weighted_fit(train,d)
                alpha=min(SHRINK,key=lambda a:statistics.mean(brier(prob(model,x,a),y) for t,x,y in valid))
                val_loss=statistics.mean(brier(prob(model,x,alpha),y) for t,x,y in valid)
                candidates.append((val_loss,d,alpha,model))
            loss,d,alpha,model=min(candidates,key=lambda a:a[0])
            # Every model is scored on the SAME frozen fixed 1h/4h grid.
            base=weighted_fit(train,None)
            base_alpha=min(SHRINK,key=lambda a:statistics.mean(brier(prob(base,x,a),y) for t,x,y in valid))
            same=[(t,brier(prob(base,x,base_alpha),y)-brier(prob(model,x,alpha),y)) for t,x,y in test]
            r={'week_start_utc':start.isoformat(),
               'selected_halflife_days':d,'selected_shrink':alpha,
               'previous_validation_Brier':loss,
               'n_independent_fixed_grid_due':len(test),
               'fixed_grid_utc_minutes':n*5,
               'selected_model':score(test,model,alpha),
               'full_history_base':score(test,base,base_alpha),
               'paired_selected_vs_full_history_Brier_gain':daily_gain(same),
               'no_future_fit':True}
            folds.append(r)
            print('RECENCY_REGIME',head,str(start.date()),'selected_days',d,
                  'fixed_due',len(test),'proper_Brier_gain_vs_same_full_history',
                  round(r['paired_selected_vs_full_history_Brier_gain']['mean_daily_gain'],7),flush=True)
        all_scores[head]={'folds':folds,
            'positive_folds_of_regime_against_full_history':sum(x['paired_selected_vs_full_history_Brier_gain']['mean_daily_gain']>0 for x in folds)}
    return {'schema':'btc-v7r6-causal-recency-regime-mathematical-test-v1',
       'all_historical_known_not_prospective':True,
       'no_production_model_change':True,'no_trading_authority':True,
       'half_lives_predeclared':HALF_LIVES_DAYS,'horizons':all_scores}

def run(raw,out):
    with gzip.open(raw,'rt') as f:rows=json.load(f)
    obj=evaluate(rows)
    obj['raw_sha256']=hashlib.sha256(pathlib.Path(raw).read_bytes()).hexdigest()
    pathlib.Path(out).write_text(json.dumps(obj,sort_keys=True,indent=2,allow_nan=False)+'\n')
    for h,r in obj['horizons'].items():print('RECENCY_SUMMARY',h,'positive_weeks',r['positive_folds_of_regime_against_full_history'],flush=True)
    return obj
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--raw',required=True);p.add_argument('--out',required=True)
    x=p.parse_args();run(x.raw,x.out)
