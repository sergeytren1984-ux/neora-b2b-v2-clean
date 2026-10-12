"""Single-line v7R6 mathematical check: is historical taker flow useful
for predicting forward BTC price drift at *execution* time?

No infrastructure, no fitted live weights. TRAIN ends 2026-09-28 with label
embargo, validation until 2026-10-05, already-seen test Oct 5-11. Outputs
explicitly research-only. Standard-library causal ridge, TRAIN-standardized,
SHRINK selected only on validation. A null result is a result, not admission.
"""
from __future__ import annotations
import argparse,datetime as dt,gzip,hashlib,json,math,pathlib,statistics
from btc_skill_rebuild.research_distribution_v7r6 import TRAIN_CUTOFF,VALIDATION_CUTOFF,STEP,UTC,BUDGET

# All features use ONLY closed candles <= source index.
FEATURES=('mom_15m','mom_1h','mom_4h','mom_12h','trend_acceleration_1h',
          'taker_5m','taker_15m','taker_1h','taker_3h_delta',
          'volume_15m_ratio','trade_count_15m_ratio','volatility_1h',
          'volatility_4h','upper_distance_1h','lower_distance_1h',
          'time_sin','time_cos')
LAMBDA=30.0
SHRINK=(0.,0.25,0.5,0.75,1.)
HEADS={'price_1h':(12,12),'price_4h':(48,48),'price_24h':(288,288),
       'OTC_execution_t60':(12,12),'OTC_wait_increment_t60_to_t120':(12,24)}

def solve(a,b):
    n=len(b)
    a=[r[:] + [v] for r,v in zip(a,b)]
    for i in range(n):
        pivot=max(range(i,n),key=lambda j:abs(a[j][i]))
        if abs(a[pivot][i])<1e-12:raise ValueError('rank deficient normal equations')
        a[i],a[pivot]=a[pivot],a[i]
        div=a[i][i]
        for k in range(i,n+1):a[i][k]/=div
        for j in range(n):
            if j==i:continue
            f=a[j][i]
            if f:
                for k in range(i,n+1):a[j][k]-=f*a[i][k]
    return [r[-1] for r in a]

def fit_ridge(train,penalty=LAMBDA):
    if len(train)<1000:raise ValueError('insufficient chronologically embargoed TRAIN rows')
    xs=[x for _,x,_ in train];ys=[y for _,_,y in train]
    k=len(xs[0]);m=[statistics.mean(x[j] for x in xs) for j in range(k)]
    s=[max(math.sqrt(statistics.mean((x[j]-m[j])**2 for x in xs)),1e-5)
       for j in range(k)]
    p=k+1;a=[[0.]*p for _ in range(p)];rhs=[0.]*p
    for x,y in zip(xs,ys):
        z=[1.]+[max(-8.,min(8.,(v-c)/vscale)) for v,c,vscale in zip(x,m,s)]
        for i in range(p):
            rhs[i]+=z[i]*y
            for j in range(i,p):a[i][j]+=z[i]*z[j]
    for i in range(p):
        if i:a[i][i]+=penalty
        for j in range(i):a[i][j]=a[j][i]
    return m,s,solve(a,rhs)

def predict(model,x):
    m,s,beta=model
    return beta[0]+sum(w*max(-8.,min(8.,(v-c)/scale))
                       for v,c,scale,w in zip(x,m,s,beta[1:]))

def examples(rows):
    if len(rows)<12000:raise ValueError('incomplete historic spot')
    t=[int(r[0]) for r in rows]
    if any(t[i]-t[i-1]!=STEP for i in range(1,len(t))):raise ValueError('future/data gap')
    cl=[];hi=[];lo=[];vol=[];buy=[];trades=[]
    for r in rows:
        if int(r[6])+1!=int(r[0])+STEP:raise ValueError('unclosed 5m candle')
        o,h,l,c,v,b,z=map(float,(r[1],r[2],r[3],r[4],r[5],r[9],r[8]))
        if not(all(math.isfinite(v) for v in (o,h,l,c,v,b,z)) and
               0<l<=min(o,c)<=max(o,c)<=h and 0<=b<=v and z>=0):
            raise ValueError('invalid OHLCV signed taker amount')
        cl.append(c);hi.append(h);lo.append(l);vol.append(v);buy.append(b);trades.append(z)
    lg=list(map(math.log,cl))
    v_sq=[0.]
    for i in range(1,len(lg)):v_sq.append(v_sq[-1]+(lg[i]-lg[i-1])**2)
    def cum(v):
        o=[0.]
        for z in v:o.append(o[-1]+z)
        return o
    vv=cum(vol);bb=cum(buy);tt=cum(trades)
    def sum12(c,i,n):return c[i+1]-c[i-n+1]
    result=[]
    for i in range(289,len(t)-288):
        at=t[i]+STEP
        buy_ratio=lambda n:sum12(bb,i,n)/max(sum12(vv,i,n),1e-8)
        fr5=buy_ratio(1);fr15=buy_ratio(3);fr60=buy_ratio(12)
        mom=lambda n:lg[i]-lg[i-n]
        last15v=sum12(vv,i,3);last15t=sum12(tt,i,3)
        prior60v=sum12(vv,i-3,12);prior60t=sum12(tt,i-3,12)
        when=dt.datetime.fromtimestamp(at/1000,UTC)
        angle=2*math.pi*(when.hour*60+when.minute)/1440
        f=(mom(3),mom(12),mom(48),mom(144),mom(12)-mom(24)+mom(12),
           2*fr5-1,2*fr15-1,2*fr60-1,2*(fr15-fr60),
           math.log((last15v+1)/(prior60v/4+1)),
           math.log((last15t+1)/(prior60t/4+1)),
           math.sqrt(max(0.,v_sq[i]-v_sq[i-12])),
           math.sqrt(max(0.,v_sq[i]-v_sq[i-48])),
           (cl[i]-max(hi[i-12:i]))/cl[i],
           (cl[i]-min(lo[i-12:i]))/cl[i],
           math.sin(angle),math.cos(angle))
        assert len(f)==len(FEATURES)
        # Target is execution closing candle. Index i+12 means +60m.
        # Current source is candle i, time issued=t[i]+STEP.
        result.append((i,at,f,cl,lg))
    return result

def scored(rows,h,shrink,model):
    out=[]
    for start,x,y,ref,at in rows:
        yhat=shrink*predict(model,x)
        p=ref*math.exp(yhat)
        # Score against persistence using exactly the same target endpoint.
        out.append((at,ref,y,p))
    return out

def per_day(values):
    d={}
    for at,v in values:
        day=dt.datetime.fromtimestamp(at/1000,UTC).date().isoformat()
        d.setdefault(day,[]).append(v)
    mean=[statistics.mean(z) for z in d.values()]
    n=len(mean)
    lo=statistics.mean(mean)-1.96*statistics.stdev(mean)/math.sqrt(n) if n>1 else None
    return {'days':n,'positive_days':sum(v>0 for v in mean),'mean_daily_gain':statistics.mean(mean),
            'lower95_day_block_normal_approx_not_prospective':lo}

def run(raw,out):
    with gzip.open(raw,'rt') as f:rows=json.load(f)
    r=examples(rows)
    tr=int(TRAIN_CUTOFF.timestamp()*1000);va=int(VALIDATION_CUTOFF.timestamp()*1000)
    heads={}
    for name,(from_i,to_i) in HEADS.items():
        dat={'train':[],'validation':[],'known_test':[]}
        for i,at,f,c,lg in r:
            end=int(rows[i+to_i][0])+STEP
            if end<tr:part='train'
            elif tr<=at and end<va:part='validation'
            elif va<=at:part='known_test'
            else:continue
            target=lg[i+to_i]-lg[i+from_i] if to_i!=from_i else lg[i+to_i]-lg[i]
            reference=c[i+from_i] if to_i!=from_i else c[i]
            dat[part].append((at,f,target,reference,c[i+to_i]))
        if min(len(dat[k]) for k in dat)<1000:raise ValueError('split too small')
        model=fit_ridge([(at,f,y) for at,f,y,_,_ in dat['train']])
        def metrics(part,sh):
            gain=[];bias=[];sign_correct=[]
            for at,f,y,ref,truth in dat[part]:
                pred=ref*math.exp(sh*predict(model,f))
                # ref is either spot now or spot at +60 for OTC pair.
                gain.append((at,abs(ref-truth)-abs(pred-truth)))
                bias.append((at,pred-truth))
                if y and predict(model,f):sign_correct.append((at,(predict(model,f)>0)==(y>0)))
            return {'n':len(gain),'point_MAE_gain_usdt':statistics.mean(v for _,v in gain),
                    'mean_prediction_bias_usdt':statistics.mean(v for _,v in bias),
                    'sign_hit_rate':statistics.mean(v for _,v in sign_correct) if sign_correct else None,
                    'day_blocks':per_day(gain)}
        selected=min(SHRINK,key=lambda z:-metrics('validation',z)['point_MAE_gain_usdt'])
        heads[name]={'lambda_ridge':LAMBDA,'validation_selected_shrink':selected,
                     'train':metrics('train',selected),
                     'validation':metrics('validation',selected),
                     'historical_test_already_seen':metrics('known_test',selected),
                     'model_coefficients_training_fit_no_claim':model[2]}
    output={'schema':'btc-v7r6-execution-drift-math-research-v1',
        'trained_using_only_closed_historical_5m':True,
        'history_already_used_by_multiple_old_model_iterations':True,
        'source_gzip_sha256':hashlib.sha256(pathlib.Path(raw).read_bytes()).hexdigest(),
        'score_is_not_out_of_sample_prospective':True,
        'model_not_promoted':True,'trading_authority':False,
        'feature_names':FEATURES,'validation_selected_shrink_grid':SHRINK,
        'horizon_targets':HEADS,'results':heads}
    pathlib.Path(out).write_text(json.dumps(output,sort_keys=True,indent=2,allow_nan=False)+'\n')
    for name,v in heads.items():
        print('DRIFT',name,'val_shrink',v['validation_selected_shrink'],
              'val_gain',round(v['validation']['point_MAE_gain_usdt'],2),
              'known_test_gain',round(v['historical_test_already_seen']['point_MAE_gain_usdt'],2),
              'test_day_ci',v['historical_test_already_seen']['day_blocks']['lower95_day_block_normal_approx_not_prospective'],flush=True)
    return output

if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('--raw',required=True);a.add_argument('--out',required=True)
    x=a.parse_args();run(x.raw,x.out)
