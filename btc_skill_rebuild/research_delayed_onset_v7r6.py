"""Causal math test: predict a directional BTC first touch >=60m ahead.

Unlike the 1h barrier, 4h allows the requested 60m advance. Relabel the
same frozen 4h target as UP >=60m / DOWN >=60m / too-soon-or-no-event /
ambiguous. Do not reoptimize price levels or inspect October events to
change the definition. This is retrospective, not a public warning.
"""
from __future__ import annotations
import argparse,datetime as dt,gzip,json,pathlib,hashlib
from btc_skill_rebuild.research_competing_barriers_v7r6 import fit,metrics,labels,alert_score,classify_threshold,SHRINK
from btc_skill_rebuild.research_execution_drift_v7r6 import examples,STEP
from btc_skill_rebuild.research_walkforward_barriers_v7r6 import FOLDS,UTC
HORIZON_5M=48
BARRIER=.012
MIN_ADVANCE_MINUTES=60

def delayed_label(first,first_touch_close_ms,publication_close_ms):
    if first==3:return 3
    if first not in (0,1):return 2
    if first_touch_close_ms is None:raise ValueError('first barrier has no future timestamp')
    conservative_minutes=(first_touch_close_ms-STEP-publication_close_ms)/60000
    return first if conservative_minutes>=MIN_ADVANCE_MINUTES else 2

def run(rawpath,out):
    with gzip.open(rawpath,'rt') as f:raw=json.load(f)
    src=examples(raw)
    dataset=[]
    for i,at,x,cl,lg in src:
        if at%(15*60000):continue
        due=int(raw[i+HORIZON_5M][0])+STEP
        first,touch_idx=labels(raw,i,HORIZON_5M,BARRIER)
        close=int(raw[touch_idx][0])+STEP if touch_idx is not None else None
        y=delayed_label(first,close,at)
        dataset.append((at,due,x,y,close))
    results=[]
    for cutoff in FOLDS:
        start=int(cutoff.timestamp()*1000);end=start+7*86400000
        val_start=start-8*86400000;val_end=start-1*86400000
        tr=[(at,x,y,touch) for at,due,x,y,touch in dataset if due<val_start]
        va=[(at,x,y,touch) for at,due,x,y,touch in dataset if val_start<=at and due<val_end]
        te=[(at,x,y,touch) for at,due,x,y,touch in dataset if start<=at<end]
        if min(len(tr),len(va),len(te))<250:raise RuntimeError('not enough chronological data')
        model=fit(tr)
        shrink=min(SHRINK,key=lambda s:metrics(va,model,s)['four_class_brier'])
        threshold=classify_threshold(va,model,shrink)
        result={'start_utc':cutoff.isoformat(),'train_n':len(tr),'val_n':len(va),'test_n':len(te),
          'train_late_UP_prior':model[3][0], 'train_late_DOWN_prior':model[3][1],
          'shrink_from_validation':shrink,
          'val':metrics(va,model,shrink),'test':metrics(te,model,shrink),
          'alert':alert_score(te,model,shrink,threshold)}
        results.append(result)
        print('LATE_ONSET_FOLD',cutoff.date(),'brier_gain',round(result['test']['brier_gain_vs_train_prior'],6),
              'directional_gain',round(result['test']['directional_incremental_brier_gain_vs_same_conditional_volatility'],6),
              'alerts',result['alert']['signals_under_one_per_day_cap'],
              'correct_lead60',result['alert']['correct_with_lead60m'],flush=True)
    outobj={'schema':'btc-v7r6-delayed-first-passage-math-research-v1',
       'horizon':'4h','threshold_pct':1.2,'minimum_advance_minutes':MIN_ADVANCE_MINUTES,
       'source_sha256':hashlib.sha256(pathlib.Path(rawpath).read_bytes()).hexdigest(),
       'classes':['UP_FIRST_AT_LEAST_60M_AHEAD','DOWN_FIRST_AT_LEAST_60M_AHEAD',
                  'EARLY_OR_NEITHER','AMBIGUOUS_SAME_5M'],
       'train_test_split_is_chronological':True,'previously_known_history_not_prospective':True,
       'no_model_promotion':True,'no_trading_authority':True,
       'folds':results,'total_signals':sum(v['alert']['signals_under_one_per_day_cap'] for v in results),
       'total_correct_lead60':sum(v['alert']['correct_with_lead60m'] for v in results),
       'positive_brier_folds':sum(v['test']['brier_gain_vs_train_prior']>0 for v in results)}
    pathlib.Path(out).write_text(json.dumps(outobj,indent=2,sort_keys=True,allow_nan=False)+'\n')
    print('LATE_ONSET_SUMMARY',outobj['positive_brier_folds'],'/',len(FOLDS),
          'alerts',outobj['total_signals'],'correct_lead60',outobj['total_correct_lead60'],flush=True)
    return outobj

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--raw',required=True);p.add_argument('--out',required=True)
    x=p.parse_args();run(x.raw,x.out)
