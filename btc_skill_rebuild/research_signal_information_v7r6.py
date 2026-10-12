"""Mathematical v7R6 ablation: does signed buy-side pressure add information
ABOVE a volatility/risk-only forecast, on the SAME next event and as-of bar?

Pre-specified groups; four untouched chronological forward test weeks,
rolling TRAIN plus previous validation embargo; no new production model.
Evaluates (a) 4-class proper scoring, (b) conditional direction after touch,
(c) conservative independent 1h/4h decision-grid and daily paired gains.
The test weeks are HISTORICAL AND SEEN. Never claim prospective skill.
"""
from __future__ import annotations
import argparse,datetime as dt,gzip,json,hashlib,math,pathlib,statistics
from btc_skill_rebuild.research_execution_drift_v7r6 import examples,STEP,FEATURES
from btc_skill_rebuild.research_competing_barriers_v7r6 import (
    fit,prob,labels,SHRINK)
from btc_skill_rebuild.research_walkforward_barriers_v7r6 import FOLDS,UTC

# Predeclare ablation groups before any scores are inspected.
# Equal-row, equal-target, equal classifier/hyperparameter geometry.
GROUPS={
    'volatility_activity_only':(9,10,11,12,13,14,15,16),
    'price_trend_plus_volatility':(0,1,2,3,4,9,10,11,12,13,14,15,16),
    'signed_flow_only':(5,6,7,8),
    'full_signed_flow_plus_volatility':tuple(range(len(FEATURES))),
}
HEADS={'1h':(12,.007),'4h':(48,.012)}


def brier(p,y):return sum((v-(j==y))**2 for j,v in enumerate(p))/4

def directional_loss(p,y):
    # Conditional directional Brier requires the direction to be a resolved
    # first-touch event; no assumption for NEITHER / AMBIGUOUS candles.
    if y not in (0,1):return None
    strength=p[0]+p[1]
    if strength<=0:return None
    return (p[0]/strength-(y==0))**2


def daily_gain(paired):
    vals={}
    for t,v in paired:
        day=dt.datetime.fromtimestamp(t/1000,UTC).date().isoformat()
        vals.setdefault(day,[]).append(v)
    days=[statistics.mean(v) for day,v in sorted(vals.items())]
    if not days:raise ValueError('empty daily gain blocks')
    mean=statistics.mean(days)
    lo=mean-1.96*statistics.stdev(days)/math.sqrt(len(days)) if len(days)>1 else None
    return {'days':len(days),'positive_days':sum(v>0 for v in days),
            'mean_daily_gain':mean,'descriptive_L95':lo}


def evaluate_folds(rows):
    feats=examples(rows)
    all_heads={}
    for head,(steps,barrier) in HEADS.items():
        source=[]
        for i,t,x,cl,log in feats:
            if t%(15*60000) or i+steps>=len(rows):continue
            outcome,touch=labels(rows,i,steps,barrier)
            mature=int(rows[i+steps][0])+STEP
            source.append((t,mature,x,outcome))
        folds=[]
        for start in FOLDS:
            begin=int(start.timestamp()*1000);end=begin+7*86400000
            valid_begin=begin-8*86400000;valid_end=begin-86400000
            train=[(t,x,y) for t,due,x,y in source if due<valid_begin]
            valid=[(t,x,y) for t,due,x,y in source if valid_begin<=t and due<valid_end]
            test=[(t,x,y) for t,due,x,y in source if begin<=t<end]
            if min(len(train),len(valid),len(test))<300:raise ValueError('incomplete chronological fold')
            predictions={};model_metadata={}
            for key,indices in GROUPS.items():
                reduce=lambda r:(r[0],tuple(r[1][j] for j in indices),r[2])
                ttrain=list(map(reduce,train));tvalid=list(map(reduce,valid))
                candidate=fit([(t,x,y,None) for t,x,y in ttrain])
                choose=min(SHRINK,key=lambda v:statistics.mean(
                    brier(prob(candidate,x,v),y) for t,x,y in tvalid))
                predictions[key]=[prob(candidate,tuple(x[j] for j in indices),choose)
                                  for t,x,y in test]
                model_metadata[key]={'validation_selected_shrink':choose,
                                     'train_n':len(train),'validation_n':len(valid)}
            first='volatility_activity_only'
            full='full_signed_flow_plus_volatility'
            price='price_trend_plus_volatility'
            flow='signed_flow_only'
            daily={};scores={}
            for name,values in predictions.items():
                scores[name]={
                    'brier':statistics.mean(brier(p,y) for (t,x,y),p in zip(test,values)),
                    'cond_direction_brier':statistics.mean([
                        directional_loss(p,y) for (t,x,y),p in zip(test,values)
                        if y in (0,1)]),
                    'n_first_touch_events':sum(y in (0,1) for t,x,y in test),
                    'n_independent_UTC_day_blocks':len({dt.datetime.fromtimestamp(t/1000,UTC).date() for t,x,y in test}),
                    **model_metadata[name]}
            for compare in ((full,first),(full,price),(flow,first)):
                a,b=compare
                improvements=[(t,brier(p0,y)-brier(p1,y))
                              for (t,x,y),p1,p0 in zip(test,predictions[a],predictions[b])]
                independently_relevant=[(t,directional_loss(p0,y)-directional_loss(p1,y))
                              for (t,x,y),p1,p0 in zip(test,predictions[a],predictions[b]) if y in (0,1)]
                pairname=a+' MINUS '+b
                daily[pairname]={
                    'proper_multiclass_score_gain_positive_better':daily_gain(improvements),
                    'conditional_direction_brier_gain_positive_better':daily_gain(independently_relevant)}
            # Non-overlapping pre-fixed clock permits an effective-sample
            # check without ever selecting an event time ex post. A 1h grid
            # has <=24 due decisions/day; a 4h grid has <=6/day. Both
            # policies use the SAME exact frozen timestamps and outcomes.
            fixed_idx=[j for j,(t,x,y) in enumerate(test)
                       if t%(steps*STEP)==0]
            fixed_comparisons={}
            for one,zero in ((full,first),(full,price),(flow,first)):
                direct=[];proper=[]
                for j in fixed_idx:
                    t,x,y=test[j]
                    p=predictions[one][j];b=predictions[zero][j]
                    proper.append((t,brier(b,y)-brier(p,y)))
                    if y in (0,1):
                        direct.append((t,directional_loss(b,y)-directional_loss(p,y)))
                fixed_comparisons[one+' MINUS '+zero]={
                    'paired_multiclass_gain':daily_gain(proper),
                    'paired_conditional_direction_gain':daily_gain(direct) if direct else None,
                    'fixed_grid_due_decisions':len(fixed_idx),
                    'resolved_directional_fixed_decisions':len(direct),
                    'precommitted_clock_minutes':steps*5,
                    'same_UTC_anchor_and_future_outcome':True}
            folds.append({'week_start_utc':start.isoformat(),
                 'train_n':len(train),'validation_n':len(valid),'forward_n':len(test),
                 'comparators':scores,'paired_same_grid':daily,
                 'nonoverlapping_fixed_grid':fixed_comparisons})
            print('NONOVERLAPPING_FLOW_INFORMATION',head,str(start.date()),
                  'due',len(fixed_idx),'directional_due',
                  fixed_comparisons[full+' MINUS '+first]['resolved_directional_fixed_decisions'],
                  'direction_brier_gain',
                  (round(fixed_comparisons[full+' MINUS '+first]['paired_conditional_direction_gain']['mean_daily_gain'],7)
                   if fixed_comparisons[full+' MINUS '+first]['paired_conditional_direction_gain'] else 'NO_EVENTS'),flush=True)
            print('SIGNED_FLOW_INFORMATION',head,str(start.date()),
                  'full_vs_volatility_brier_gain',round(daily[full+' MINUS '+first]['proper_multiclass_score_gain_positive_better']['mean_daily_gain'],7),
                  'full_vs_volatility_cond_dir_gain',round(daily[full+' MINUS '+first]['conditional_direction_brier_gain_positive_better']['mean_daily_gain'],7),
                  'full_vs_price_brier_gain',round(daily[full+' MINUS '+price]['proper_multiclass_score_gain_positive_better']['mean_daily_gain'],7),flush=True)
        all_heads[head]={'folds':folds,'n_mathematically_separate_weekly_forward_blocks':len(folds),
          'full_vs_volatility_weeks_winning_brier':sum(
               f['paired_same_grid'][full+' MINUS '+first]['proper_multiclass_score_gain_positive_better']['mean_daily_gain']>0 for f in folds),
          'full_vs_price_weeks_winning_brier':sum(
               f['paired_same_grid'][full+' MINUS '+price]['proper_multiclass_score_gain_positive_better']['mean_daily_gain']>0 for f in folds)}
    return {'schema':'btc-v7r6-spot-pressure-ablation-mathematics-v1',
         'scored_historic_data_already_seen':True,
         'same_frozen_4way_first_touch_targets':True,
         'same_training_validation_forward_windows_for_all_groups':True,
         'comparison_of_correlated_windows_not_independent_events':True,
         'group_feature_indices':GROUPS,'not_promoted_to_live':True,
         'trade_authority':False,'horizons':all_heads}

def run(raw,out):
    with gzip.open(raw,'rt') as f:rows=json.load(f)
    v=evaluate_folds(rows)
    v['raw_gzip_sha256']=hashlib.sha256(pathlib.Path(raw).read_bytes()).hexdigest()
    pathlib.Path(out).write_text(json.dumps(v,indent=2,sort_keys=True,allow_nan=False)+'\n')
    for head,result in v['horizons'].items():
        print('PRESSURE_ABLATION_SUMMARY',head,'FULL_BEATS_VOL_IN',result['full_vs_volatility_weeks_winning_brier'],'OF 4 WEEKS',
              'FULL_BEATS_PRICE_IN',result['full_vs_price_weeks_winning_brier'],'OF 4 WEEKS',flush=True)
    return v

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--raw',required=True);p.add_argument('--out',required=True)
    x=p.parse_args();run(x.raw,x.out)
