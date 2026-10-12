"""Causal 24h three-way endpoint research for the *existing* BTC v7R6 math.

Labels exactly 24 hours after publication: UP>=2%, DOWN<=-2%, RANGE.
No future bars used to calculate inputs, future endpoint maturity embargoes
train/validation. This is a historical mathematical diagnostic; it DOES NOT
retroactively create prospective forecasts or change frozen v7R6.
"""
from __future__ import annotations
import argparse,datetime as dt,gzip,hashlib,json,math,pathlib,statistics
from btc_skill_rebuild.research_execution_drift_v7r6 import examples,STEP
from btc_skill_rebuild.research_walkforward_barriers_v7r6 import FOLDS,UTC
from btc_skill_rebuild.research_competing_barriers_v7r6 import (
    normalized,standardize,softmax,SHRINK,WEIGHT_DECAY,EPOCHS,LEARNING_RATE)
STEPS=288
LIMIT=.02
LABELS=('UP','DOWN','RANGE')


def target(reference,forward):
    if not (math.isfinite(reference) and math.isfinite(forward) and min(reference,forward)>0):
        raise ValueError('bad historical BTC prices')
    if forward>=reference*(1+LIMIT):return 0
    if forward<=reference*(1-LIMIT):return 1
    return 2


def fit(train):
    if len(train)<1500:raise ValueError('not enough causal history')
    mean,scale=standardize(train)
    X=[normalized(x,mean,scale) for _,x,_ in train]
    y=[a for _,_,a in train]
    n=len(y);k=3
    if any(a not in range(k) for a in y):raise ValueError('wrong 24h label')
    pri=[(sum(a==j for a in y)+1)/(n+k) for j in range(k)]
    d=len(X[0]);beta=[[0.]*d for _ in range(k)]
    for j,p in enumerate(pri):beta[j][0]=math.log(p)
    for epoch in range(EPOCHS):
        grad=[[0.]*d for _ in range(k)]
        for xx,actual in zip(X,y):
            p=softmax([sum(z*t for z,t in zip(b,xx)) for b in beta])
            for j in range(k):
                err=p[j]-(j==actual)
                for z in range(d):grad[j][z]+=err*xx[z]
        rate=LEARNING_RATE*(1-.55*epoch/EPOCHS)
        for j in range(k):
            for z in range(d):
                penalty=WEIGHT_DECAY*beta[j][z] if z else 0.
                beta[j][z]-=rate*(grad[j][z]/n+penalty/n)
    return mean,scale,beta,pri


def predict(model,x,shrink):
    mean,scale,beta,prior=model
    norm=normalized(x,mean,scale)
    p=softmax([sum(w*a for w,a in zip(b,norm)) for b in beta])
    p=[(1-shrink)*q+shrink*v for v,q in zip(p,prior)]
    if not all(math.isfinite(z) and 0<=z<=1 for z in p) or abs(sum(p)-1)>1e-9:
        raise ValueError('24h invalid probabilities')
    return p


def brier(p,y):return sum((p[j]-(j==y))**2 for j in range(3))/3


def evaluate(sample,model,shrink):
    gains=[];direction=[];days={};riskdays={};events=[0,0,0]
    for timestamp,x,y in sample:
        p=predict(model,x,shrink);q=model[3]
        events[y]+=1
        gain=brier(q,y)-brier(p,y)
        risk=p[0]+p[1]
        up_ratio=q[0]/(q[0]+q[1])
        no_direction=[risk*up_ratio,risk*(1-up_ratio),p[2]]
        dg=brier(no_direction,y)-brier(p,y)
        day=dt.datetime.fromtimestamp(timestamp/1000,UTC).date().isoformat()
        gains.append(gain);direction.append(dg)
        days.setdefault(day,[]).append(gain)
        riskdays.setdefault(day,[]).append(dg)
    mean_by_day=[statistics.mean(v) for _,v in sorted(days.items())]
    mean_dir_day=[statistics.mean(v) for _,v in sorted(riskdays.items())]
    def bound(v):return (statistics.mean(v)-1.96*statistics.stdev(v)/math.sqrt(len(v))) if len(v)>1 else None
    return {'n_overlap_15m':len(sample),'n_distinct_UTC_days':len(mean_by_day),
            'counts_UP_DOWN_RANGE':events,
            'brier_gain_vs_train_prior':statistics.mean(gains),
            'direction_increment_brier_vs_same_event_probability':statistics.mean(direction),
            'days_improved_total':sum(x>0 for x in mean_by_day),
            'days_improved_direction':sum(x>0 for x in mean_dir_day),
            'total_brier_gain_day_L95_descriptive':bound(mean_by_day),
            'direction_day_L95_descriptive':bound(mean_dir_day)}


def alert_score(sample,model,shrink,val):
    if shrink<=0:
        return {"historical_unpublished_alerts":0,"correct_direction_endpoint":0,"opposite_direction":0,"threshold_selected_on_past_validation":None,"reason":"zero directional model weight: constant TRAIN prior is not a predictive warning"}
    strengths=sorted(max(predict(model,x,shrink)[:2]) for _,x,_ in val)
    val_days=len({dt.datetime.fromtimestamp(ts/1000,UTC).date() for ts,_,_ in val})
    target=max(1,len(val)/val_days)
    threshold=(strengths[int((1-min(1.,1/target))*(len(strengths)-1))]
               if strengths[-1]-strengths[0]>1e-12 else None)
    seen=set();issued=hits=opposite=0
    for t,x,y in sample:
        pp=predict(model,x,shrink)
        if threshold is None or max(pp[:2])<=threshold:continue
        day=dt.datetime.fromtimestamp(t/1000,UTC).date().isoformat()
        if day in seen:continue
        seen.add(day);issued+=1
        predicted=0 if pp[0]>=pp[1] else 1
        hits+=predicted==y
        opposite+=(y in (0,1) and predicted!=y)
    return {'historical_unpublished_alerts':issued,'correct_direction_endpoint':hits,
            'opposite_direction':opposite,'threshold_selected_on_past_validation':threshold}


def run(source,out):
    with gzip.open(source,'rt') as f:rows=json.load(f)
    raw=examples(rows)
    population=[]
    for i,asof,x,cl,log in raw:
        if asof%(15*60000) or i+STEPS>=len(rows):continue
        due=int(rows[i+STEPS][0])+STEP
        y=target(cl[i],float(rows[i+STEPS][4]))
        population.append((asof,due,x,y))
    results=[]
    for fold in FOLDS:
        at=int(fold.timestamp()*1000);end=at+7*86400000
        valstart=at-8*86400000;valend=at-86400000
        train=[(t,x,y) for t,due,x,y in population if due<valstart]
        valid=[(t,x,y) for t,due,x,y in population if valstart<=t and due<valend]
        future=[(t,x,y) for t,due,x,y in population if at<=t<end]
        if min(map(len,(train,valid,future)))<250:raise ValueError('incomplete 24h validation')
        m=fit(train)
        shrink=min(SHRINK,key=lambda a:-evaluate(valid,m,a)['brier_gain_vs_train_prior'])
        outcome=evaluate(future,m,shrink)
        signals=alert_score(future,m,shrink,valid)
        results.append({'test_week_start_utc':fold.isoformat(),'train_n':len(train),
            'validation_n':len(valid),'frozen_prior':m[3],'chosen_validation_shrink':shrink,
            'validation':evaluate(valid,m,shrink),'historical_future':outcome,
            'historical_signals':signals})
        print('24H_ENDPOINT_MATH',str(fold.date()),'gain',round(outcome['brier_gain_vs_train_prior'],7),
              'direction',round(outcome['direction_increment_brier_vs_same_event_probability'],7),
              'alerts',signals['historical_unpublished_alerts'],
              'correct',signals['correct_direction_endpoint'],flush=True)
    obj={'schema':'btc-v7r6-existing-three-way-24h-endpoint-research-v1',
         'labels_order':LABELS,'end_price_threshold_pct':2.,'fixed_24h_maturity':True,
         'input_source_sha256':hashlib.sha256(pathlib.Path(source).read_bytes()).hexdigest(),
         'all_forward_weeks_historical_already_seen':True,'has_signed_future_forecasts':False,
         'production_code_modified':False,'trading_authority':False,'folds':results}
    pathlib.Path(out).write_text(json.dumps(obj,indent=2,ensure_ascii=False,sort_keys=True,allow_nan=False)+'\n')
    print('24H_POSITIVE_FOLDS',sum(r['historical_future']['brier_gain_vs_train_prior']>0 for r in results),
          'DIRECTION_POSITIVE_FOLDS',sum(r['historical_future']['direction_increment_brier_vs_same_event_probability']>0 for r in results),flush=True)
    return obj

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--raw',required=True);p.add_argument('--out',required=True)
    a=p.parse_args();run(a.raw,a.out)
