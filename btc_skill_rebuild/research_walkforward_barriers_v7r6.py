"""Historical rolling-origin competition audit; no live deployment.

Each 7-day forward block has TRAIN preceding it and an independent preceding
validation week (with horizon maturity embargo). Never tune after seeing a
forward block. Overlap in rolling TRAIN is allowed, forward TEST blocks do
not overlap; statistical uncertainty uses UTC day means, NOT 15m slots.
"""
from __future__ import annotations
import argparse,datetime as dt,gzip,json,math,pathlib,statistics,hashlib
from btc_skill_rebuild.research_competing_barriers_v7r6 import (
    HORIZONS,SHRINK,fit,metrics,labels,alert_score,classify_threshold)
from btc_skill_rebuild.research_execution_drift_v7r6 import examples,STEP
UTC=dt.timezone.utc
FOLDS=(dt.datetime(2026,9,14,tzinfo=UTC),
       dt.datetime(2026,9,21,tzinfo=UTC),
       dt.datetime(2026,9,28,tzinfo=UTC),
       dt.datetime(2026,10,5,tzinfo=UTC))

def forward(rows):
    inputs=examples(rows)
    all_heads={}
    for name,(n,band) in HORIZONS.items():
        indexed=[]
        for i,at,f,cl,lgs in inputs:
            if at%(15*60000):continue
            if i+n>=len(rows):continue
            end=int(rows[i+n][0])+STEP
            y,touch=labels(rows,i,n,band)
            indexed.append((at,end,f,y,int(rows[touch][0])+STEP if touch is not None else None))
        summaries=[];all_days=[]
        for cutoff in FOLDS:
            start=int(cutoff.timestamp()*1000)
            end=start+7*86400000
            validation_start=start-8*86400000
            validation_end=start-1*86400000
            train=[(at,x,y,touch) for at,done,x,y,touch in indexed
                   if done<validation_start]
            validate=[(at,x,y,touch) for at,done,x,y,touch in indexed
                      if validation_start<=at and done<validation_end]
            test=[(at,x,y,touch) for at,done,x,y,touch in indexed
                  if start<=at<end and done<=min(end, int(rows[-1][0])+STEP)]
            if not (len(train)>2000 and len(validate)>400 and len(test)>250):
                raise ValueError('not enough data in chronologically blocked fold')
            model=fit(train)
            shrink=min(SHRINK,key=lambda a:metrics(validate,model,a)['four_class_brier'])
            threshold=classify_threshold(validate,model,shrink)
            sample=metrics(test,model,shrink)
            alerts=alert_score(test,model,shrink,threshold)
            summaries.append({'start_utc':cutoff.isoformat(),
                              'train_n':len(train),'validation_n':len(validate),
                              'forward_n':len(test),'validation_shrink':shrink,
                              'baseline_prior':model[3],
                              'sample':sample,'alerts':alerts})
            all_days.append((cutoff.date().isoformat(),sample['brier_gain_vs_train_prior'],
                             sample['directional_incremental_brier_gain_vs_same_conditional_volatility']))
        # Across disjoint forward periods, fold means are coarse diagnostics;
        # this historical 4-fold study was made AFTER Oct 11 data were seen.
        all_heads[name]={
            'four_disjoint_seven_day_forward_folds':summaries,
            'all_historical_no_new_prospective_periods':True,
            'folds_positive_brier_gain':sum(f['sample']['brier_gain_vs_train_prior']>0 for f in summaries),
            'total_forward_closed_15m_slots':sum(f['forward_n'] for f in summaries),
            'total_alerts_not_public':sum(f['alerts']['signals_under_one_per_day_cap'] for f in summaries),
            'total_correct_first_barrier':sum(f['alerts']['correct_first_barrier'] for f in summaries),
            'total_correct_at_least_30m_before_touch':sum(f['alerts']['correct_with_lead30m'] for f in summaries),
            'total_correct_at_least_60m_before_touch':sum(f['alerts']['correct_with_lead60m'] for f in summaries),
        }
    return {'schema':'btc-v7r6-mathematical-historical-walk-forward-v1',
            'barrier_labels':'UP_FIRST/DOWN_FIRST/NEITHER/AMBIGUOUS_SAME_5M',
            'fully_historical_after_known_11_oct_incident':True,
            'not_live_public_alerts':True,
            'no_predictive_trade_authority':True,
            'per_horizon':all_heads}

def run(path,out):
    with gzip.open(path,'rt') as f:rows=json.load(f)
    r=forward(rows)
    r['source_sha256']=hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()
    pathlib.Path(out).write_text(json.dumps(r,indent=2,sort_keys=True,allow_nan=False)+'\n')
    for name,v in r['per_horizon'].items():
        print('WALK_FORWARD',name,'positive_folds',v['folds_positive_brier_gain'],
            'total_slots',v['total_forward_closed_15m_slots'],
            'alerts',v['total_alerts_not_public'],
            'correct',v['total_correct_first_barrier'],
            'lead30',v['total_correct_at_least_30m_before_touch'],
            'lead60',v['total_correct_at_least_60m_before_touch'],flush=True)
        for f in v['four_disjoint_seven_day_forward_folds']:
            print('FOLD',name,f['start_utc'][:10],
                  'valshrink',f['validation_shrink'],
                  'brier_gain',round(f['sample']['brier_gain_vs_train_prior'],6),
                  'directional_gain',round(f['sample']['directional_incremental_brier_gain_vs_same_conditional_volatility'],6),
                  'alerts',f['alerts']['signals_under_one_per_day_cap'],
                  'correct',f['alerts']['correct_first_barrier'],flush=True)
    return r
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--raw',required=True);p.add_argument('--out',required=True)
    a=p.parse_args();run(a.raw,a.out)
