"""Existing v7R6 3-way endpoint forecaster, reusing its SINGLE frozen maths.

Apply the same regularized softmax as research_endpoint_24h to all 1h/4h/24h
endpoint tasks. Do not invent a second model: same features/fit/predict,
only preregistered label maturity and thresholds differ by head.

Separate endpoint UP/DOWN/RANGE from *first-barrier crossing*; those events
are NOT interchangeable. Publish-time target is fixed slot+N hours;
proposed real publication delay reduces actionable lead, not extend target.
Historical spot closed5m 65-day data are already seen; results research-only.
"""
from __future__ import annotations
import argparse,datetime as dt,gzip,json,hashlib,math,pathlib,statistics
from btc_skill_rebuild.research_execution_drift_v7r6 import examples,STEP
from btc_skill_rebuild.research_endpoint_24h_v7r6 import fit,predict,brier,LABELS
from btc_skill_rebuild.research_competing_barriers_v7r6 import SHRINK
from btc_skill_rebuild.research_walkforward_barriers_v7r6 import FOLDS,UTC

# Frozen before fold inspection, matching previously established directional
# barrier magnitudes but endpoint != first touch. Literal values not selected
# on October 5-11 observations.
HORIZONS={'1h':(12,.007),'4h':(48,.012),'24h':(288,.02)}


def endpoint_class(reference,forward,threshold):
    if not all(math.isfinite(v) for v in (reference,forward,threshold)) or min(reference,forward)<=0 or threshold<=0:
        raise ValueError('invalid BTC endpoint or label threshold')
    return 0 if forward>=reference*(1+threshold) else 1 if forward<=reference*(1-threshold) else 2


def daily_scores(test,model,shrink):
    obs=[];pr=[];cpr=[];dir_brier=[];byday={};counts=[0,0,0]
    for t,x,y in test:
        p=predict(model,x,shrink);q=model[3]
        counts[y]+=1
        score=brier(p,y);base=brier(q,y)
        obs.append(score);pr.append(base)
        risk=p[0]+p[1]
        share=q[0]/(q[0]+q[1])
        non_direct=[risk*share,risk*(1-share),p[2]]
        dir_brier.append(brier(non_direct,y)-score)
        key=dt.datetime.fromtimestamp(t/1000,UTC).date().isoformat()
        byday.setdefault(key,[]).append(base-score)
    mean=[statistics.mean(v) for v in byday.values()]
    lower=(statistics.mean(mean)-1.96*statistics.stdev(mean)/math.sqrt(len(mean)) if len(mean)>1 else None)
    return {'n':len(test),'n_days':len(mean),'up_down_range':counts,
            'brier':statistics.mean(obs),'train_prior_brier':statistics.mean(pr),
            'gain_vs_same_train_prior':statistics.mean(b-a for a,b in zip(obs,pr)),
            'signed_direction_increment_brier_vs_identical_event_risk':statistics.mean(dir_brier),
            'positive_daily_gain_blocks':sum(v>0 for v in mean),
            'descriptive_daily_lower95':lower}


def evaluate(rows):
    candles=examples(rows)
    results={}
    for h,(duration,threshold) in HORIZONS.items():
        population=[]
        for i,t,x,close,lg in candles:
            if t%(15*60000) or i+duration>=len(rows):continue
            matured=int(rows[i+duration][0])+STEP
            y=endpoint_class(close[i],float(rows[i+duration][4]),threshold)
            population.append((t,matured,x,y))
        folds=[]
        for fold in FOLDS:
            at=int(fold.timestamp()*1000);end=at+7*86400000
            valid_start=at-8*86400000;valid_end=at-86400000
            train=[(t,x,y) for t,due,x,y in population if due<valid_start]
            valid=[(t,x,y) for t,due,x,y in population if valid_start<=t and due<valid_end]
            forward=[(t,x,y) for t,due,x,y in population if at<=t<end]
            fixed=[(t,x,y) for t,x,y in forward if t%(duration*STEP)==0]
            # Count EVERY predeclared future-clock decision, even when the
            # archive ends before its target has actually matured. The
            # incomplete last October week must not vanish silently.
            expected_fixed_due=(7*24*60)//(duration*5)
            missing_fixed_due=expected_fixed_due-len(fixed)
            if missing_fixed_due<0:raise ValueError('duplicate UTC fixed forecast slot')
            if min(len(train),len(valid),len(forward))<250 or len(fixed)<6:
                raise ValueError('incomplete causal endpoint research fold')
            # SAME existing softmax for every head. No fold-specific feature
            # engineering or hyperparameters; only val-selected prior shrink.
            model=fit(train)
            shrink=min(SHRINK,key=lambda a:daily_scores(valid,model,a)['brier'])
            r={'week_start_utc':fold.isoformat(),
               'n_train_matured_before_previous_validation':len(train),
               'n_previous_validation':len(valid),'n_forward_overlap':len(forward),
               'chosen_shrink_from_previous_validation':shrink,
               'training_prior':model[3],
               'validation':daily_scores(valid,model,shrink),
               'registered_fixed_due_denominator':expected_fixed_due,
               'fixed_due_outcomes_not_yet_mature_in_archive':missing_fixed_due,
               'complete_forward_fixed_due_grid':missing_fixed_due==0,
               'fixed_clock_nonoverlapping':daily_scores(fixed,model,shrink),
               'full_15min_overlap_diagnostic_only':daily_scores(forward,model,shrink),
               'forecast_anchor_at_5m_close_not_virtual_public_delivery':True}
            folds.append(r)
            print('UNIFIED_THREE_WAY',h,str(fold.date()),
                'alpha',shrink,'nonoverlap_n',len(fixed),
                'brier_gain',round(r['fixed_clock_nonoverlapping']['gain_vs_same_train_prior'],7),
                'direction_increment',round(r['fixed_clock_nonoverlapping']['signed_direction_increment_brier_vs_identical_event_risk'],7),flush=True)
        results[h]={'endpoint_threshold_pct':threshold*100,
            'fixed_UTC_end_after_slot_minutes':duration*5,
            'folds':folds,
            'positive_nonoverlap_weeks_complete_only':sum(x['complete_forward_fixed_due_grid'] and x['fixed_clock_nonoverlapping']['gain_vs_same_train_prior']>0 for x in folds),
            'positive_nonoverlap_direction_weeks_complete_only':sum(x['complete_forward_fixed_due_grid'] and x['fixed_clock_nonoverlapping']['signed_direction_increment_brier_vs_identical_event_risk']>0 for x in folds),
            'full_forward_weeks_evaluated':sum(x['complete_forward_fixed_due_grid'] for x in folds),
            'fixed_due_missing_total':sum(x['fixed_due_outcomes_not_yet_mature_in_archive'] for x in folds)}
    return {'schema':'btc-v7r6-single-mathematical-softmax-1h-4h-24h-3outcome-v1',
      'three_outcomes':LABELS,'distinct_first_touch_and_endpoint_tasks':True,
      'input_only_closed_5m_before_forecast_slot':True,
      'public_forecast_delivery_must_be_checked_separately':True,
      'all_historical_known_data_no_prospective_publications':True,
      'no_prod_changes':True,'trading_authority':False,'horizons':results}

def run(source,out):
    with gzip.open(source,'rt') as f:rows=json.load(f)
    data=evaluate(rows)
    data['historic_closed5m_gzip_sha256']=hashlib.sha256(pathlib.Path(source).read_bytes()).hexdigest()
    pathlib.Path(out).write_text(json.dumps(data,ensure_ascii=False,indent=2,sort_keys=True,allow_nan=False)+'\n')
    for h,r in data['horizons'].items():
        print('UNIFIED_THREE_WAY_SUMMARY',h,'positive_complete_weeks',r['positive_nonoverlap_weeks_complete_only'],
              'complete_weeks',r['full_forward_weeks_evaluated'],
              'missing_due',r['fixed_due_missing_total'],
              'direction_positive_complete',r['positive_nonoverlap_direction_weeks_complete_only'],flush=True)
    return data
if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('--raw',required=True);a.add_argument('--out',required=True)
    o=a.parse_args();run(o.raw,o.out)