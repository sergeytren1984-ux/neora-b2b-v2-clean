"""v7R6 mathematical research ONLY: symmetric competing BTC barrier first-touch.

Four mutually exclusive outcomes: UP_FIRST / DOWN_FIRST / NEITHER /
AMBIGUOUS_SAME_5M (candle OHLC cannot resolve order within 5m). This is
NOT the published 1m event label. Use only as-of spot OHLCV/taker; no
claims for OI/depth/macro. Evaluate 1h and 4h, not independent 24h
sample selection. TRAIN->VALIDATION->known retrospective test, no tune test.
"""
from __future__ import annotations
import argparse,datetime as dt,gzip,json,math,pathlib,statistics,hashlib
from btc_skill_rebuild.research_execution_drift_v7r6 import examples,FEATURES,STEP
from btc_skill_rebuild.research_distribution_v7r6 import TRAIN_CUTOFF,VALIDATION_CUTOFF,UTC

LABELS=('UP_FIRST','DOWN_FIRST','NEITHER','AMBIGUOUS_SAME_5M')
HORIZONS={'1h':(12,.007),'4h':(48,.012)}
WEIGHT_DECAY=0.8
EPOCHS=135
LEARNING_RATE=.14
SHRINK=(0.,.25,.5,.75,1.)

def labels(raw,i,n,band):
    current=float(raw[i][4])
    up=current*(1+band);down=current*(1-band)
    for k in range(i+1,i+n+1):
        row=raw[k]
        u=float(row[2])>=up
        d=float(row[3])<=down
        if u and d:return 3,k
        if u:return 0,k
        if d:return 1,k
    return 2,None

def standardize(train):
    xs=[r[1] for r in train]
    k=len(xs[0]);means=[statistics.mean(x[j] for x in xs) for j in range(k)]
    scale=[max(1e-4,math.sqrt(statistics.mean((x[j]-means[j])**2 for x in xs))) for j in range(k)]
    return means,scale

def normalized(x,means,scale):return [1.]+[max(-6.,min(6.,(a-m)/s)) for a,m,s in zip(x,means,scale)]

def softmax(scores):
    mid=max(scores);a=[math.exp(min(0.,v-mid)) for v in scores]
    z=sum(a)
    return [v/z for v in a]

def fit(train):
    if len(train)<1500:raise ValueError('training observations too scarce')
    mean,scale=standardize(train)
    xs=[normalized(row[1],mean,scale) for row in train]
    ys=[row[2] for row in train]
    prior=[(sum(j==k for j in ys)+1)/(len(ys)+4) for k in range(4)]
    dim=len(xs[0]);beta=[[0.]*dim for _ in range(4)]
    for j,p in enumerate(prior):beta[j][0]=math.log(p)
    for epoch in range(EPOCHS):
        grad=[[0.]*dim for _ in range(4)]
        for x,y in zip(xs,ys):
            scores=[sum(a*b for a,b in zip(row,x)) for row in beta]
            prob=softmax(scores)
            for cat in range(4):
                err=(prob[cat]-(cat==y))
                g=grad[cat]
                for z in range(dim):g[z]+=err*x[z]
        rate=LEARNING_RATE*(1-.55*epoch/EPOCHS)
        n=len(xs)
        for cat in range(4):
            for z in range(dim):
                penalty=WEIGHT_DECAY*beta[cat][z] if z else 0.
                beta[cat][z]-=rate*(grad[cat][z]/n+penalty/n)
    return (mean,scale,beta,prior)

def prob(model,x,shrink=1.):
    mean,scale,beta,prior=model
    z=normalized(x,mean,scale)
    p=softmax([sum(a*b for a,b in zip(row,z)) for row in beta])
    return [(1-shrink)*q+shrink*v for v,q in zip(p,prior)]

def metrics(sample,model,shrink):
    loss=[];brier=[];baseline=[];byday={};direction_gain=[];byday_direction={}
    historical_up_ratio=model[3][0]/(model[3][0]+model[3][1])
    directional=[]
    for at,x,y,touch in sample:
        p=prob(model,x,shrink);q=model[3]
        b=sum((v-(j==y))**2 for j,v in enumerate(p))/4
        bb=sum((v-(j==y))**2 for j,v in enumerate(q))/4
        logloss=-math.log(max(p[y],1e-12))
        # The identical model's total probability of *any* event is
        # preserved; only its directional conditional shares are removed.
        # Thus this counterfactual isolates whether signed flow and past
        # trend actually predict DIRECTION, rather than mere volatility.
        event=p[0]+p[1]
        no_direction=[event*historical_up_ratio,event*(1-historical_up_ratio),p[2],p[3]]
        risk_only_brier=sum((v-(j==y))**2 for j,v in enumerate(no_direction))/4
        brier.append(b);baseline.append(bb);loss.append(logloss)
        day=dt.datetime.fromtimestamp(at/1000,UTC).date().isoformat()
        byday.setdefault(day,[]).append(bb-b)
        direction_gain.append(risk_only_brier-b)
        byday_direction.setdefault(day,[]).append(risk_only_brier-b)
        directional.append((at,y,touch,p))
    daily=[statistics.mean(s) for s in byday.values()]
    daily_direction=[statistics.mean(s) for s in byday_direction.values()]
    return {'n_overlapping_15m_slots':len(sample),'independent_UTC_day_blocks':len(daily),
            'four_class_brier':statistics.mean(brier),
            'frozen_train_prior_brier':statistics.mean(baseline),
            'brier_gain_vs_train_prior':statistics.mean(base-g for base,g in zip(baseline,brier)),
            'log_loss':statistics.mean(loss),
            'gain_positive_days':sum(v>0 for v in daily),
            'directional_incremental_brier_gain_vs_same_conditional_volatility':statistics.mean(direction_gain),
            'directional_positive_day_blocks':sum(v>0 for v in daily_direction),
            'directional_day_lower95_descriptive':statistics.mean(daily_direction)-1.96*statistics.stdev(daily_direction)/math.sqrt(len(daily_direction)) if len(daily_direction)>1 else None,
            'daily_gain_lower95_descriptive':statistics.mean(daily)-1.96*statistics.stdev(daily)/math.sqrt(len(daily)) if len(daily)>1 else None,
            'positive_first_touch_events':sum(y in (0,1) for _,_,y,_ in sample)}

def classify_threshold(valid,model,shrink,per_day=1):
    # The event-based alert policy cannot be allowed to use test outcomes.
    strengths=[]
    for at,x,y,touch in valid:
        p=prob(model,x,shrink)
        strengths.append(max(p[0],p[1]))
    ordered=sorted(strengths)
    # If every predicted risk is identical, the probability conveys NO
    # timing/directional selection information. Quantile threshold ties
    # must never fabricate one warning per day from constant priors.
    if ordered[-1]-ordered[0]<=1e-12:
        return None
    daily=len(valid)/max(1,len(set(dt.datetime.fromtimestamp(x[0]/1000,UTC).date() for x in valid)))
    frac=per_day/max(1,daily)
    pos=int((1-min(1.,frac))*(len(ordered)-1))
    return ordered[pos]

def alert_score(sample,model,shrink,threshold):
    n=0;correct=0;lead30=0;lead60=0;opposite=0;days={}
    for at,x,y,touch in sample:
        p=prob(model,x,shrink)
        strength=max(p[0],p[1]);candidate=0 if p[0]>=p[1] else 1
        if threshold is None or strength<=threshold:continue
        # deterministic one per UTC day to match conservative frozen cap
        day=dt.datetime.fromtimestamp(at/1000,UTC).date().isoformat()
        if day in days:continue
        days[day]=1;n+=1
        if candidate==y:
            correct+=1
            # Historical OHLC only localizes the touch inside its 5m
            # candle. The earliest possible touch is candle OPEN, so
            # claiming (candle close - issue) overstates lead by 5m.
            lead=(touch-STEP-at)/60000 if touch is not None else 0
            if lead>=30:lead30+=1
            if lead>=60:lead60+=1
        elif y in (0,1):opposite+=1
    event_days=len({dt.datetime.fromtimestamp(at/1000,UTC).date()
                 for at,x,y,touch in sample if y in (0,1)})
    return {'signals_under_one_per_day_cap':n,'correct_first_barrier':correct,
            'days_with_either_unambiguous_first_barrier':event_days,
            'full_grid_directional_alert_coverage':n/len(sample),
            'precision_if_any':correct/n if n else None,
            'correct_with_lead30m':lead30,'correct_with_lead60m':lead60,
            'wrong_direction_first_touch':opposite}

def run(path,out):
    with gzip.open(path,'rt') as f:raw=json.load(f)
    inputs=examples(raw)
    c1=int(TRAIN_CUTOFF.timestamp()*1000);c2=int(VALIDATION_CUTOFF.timestamp()*1000)
    results={}
    for key,(steps,barrier) in HORIZONS.items():
        dat={'train':[],'validation':[],'known_test':[]}
        for i,at,x,cl,lg in inputs:
            if at%(15*60000):continue
            if i+steps>=len(raw):continue
            end=int(raw[i+steps][0])+STEP
            if end<c1:bucket='train'
            elif c1<=at and end<c2:bucket='validation'
            elif c2<=at:bucket='known_test'
            else:continue
            side,touch=labels(raw,i,steps,barrier)
            dat[bucket].append((at,x,side,int(raw[touch][0])+STEP if touch is not None else None))
        model=fit(dat['train'])
        selected=min(SHRINK,key=lambda s:metrics(dat['validation'],model,s)['four_class_brier'])
        threshold=classify_threshold(dat['validation'],model,selected)
        # If the selected threshold gives no alerts, display that, don't refit
        results[key]={
            'trained_before_validation_causal':True,'barrier_pct':barrier*100,
            'horizon_minutes':steps*5,
            'validation_selected_shrink':selected,
            'one_daily_alarm_validation_threshold':threshold,
            'train_prevalence':dict(zip(LABELS,model[3])),
            'train':metrics(dat['train'],model,selected),
            'validation':metrics(dat['validation'],model,selected),
            'known_historical_test':metrics(dat['known_test'],model,selected),
            'validation_alerts':alert_score(dat['validation'],model,selected,threshold),
            'known_historical_test_alerts':alert_score(dat['known_test'],model,selected,threshold)}
    r={'schema':'btc-v7r6-competing-barrier-spot-research-v1',
       'not_prospective':True,'last_week_previously_seen':True,
       'cannot_resolve_same_5m_candle_order':True,
       'no_signed_historical_derivatives':True,'data_sha256':hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest(),
       'trading_authority':False,'model_promoted':False,'results':results}
    pathlib.Path(out).write_text(json.dumps(r,sort_keys=True,indent=2,allow_nan=False)+'\n')
    for h,v in results.items():
        print('COMPETING',h,'selected_shrink',v['validation_selected_shrink'],
              'validation_gain',round(v['validation']['brier_gain_vs_train_prior'],6),
              'known_test_gain',round(v['known_historical_test']['brier_gain_vs_train_prior'],6),
              'directional_gain_val',round(v['validation']['directional_incremental_brier_gain_vs_same_conditional_volatility'],7),
              'directional_gain_test',round(v['known_historical_test']['directional_incremental_brier_gain_vs_same_conditional_volatility'],7),
              'val_alert',v['validation_alerts'],
              'test_alert',v['known_historical_test_alerts'],flush=True)
    return r

if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('--raw',required=True);a.add_argument('--out',required=True)
    x=a.parse_args();run(x.raw,x.out)