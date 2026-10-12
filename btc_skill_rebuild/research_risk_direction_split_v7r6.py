"""v7R6 single-model mathematical split: independent event risk and direction.

Four probabilities sum to 1. Baseline: 4-way volatility-activity model.
Candidate: preserve all of baseline event risk and non-event probabilities,
replace ONLY the conditional UP vs DOWN allocation by signed taker flow
learned from matured first touches. No production formulas are changed.
Four blocked rolling-origin historical weeks; only previous validation
selects shrink. Fixed non-overlapping 1h/4h decisions are the core score.
"""
from __future__ import annotations
import argparse,datetime as dt,gzip,json,hashlib,math,pathlib,statistics
from btc_skill_rebuild.research_competing_barriers_v7r6 import fit,prob,labels,SHRINK
from btc_skill_rebuild.research_conditional_direction_v7r6 import train_direction,direction_up
from btc_skill_rebuild.research_signal_information_v7r6 import GROUPS,brier,directional_loss,daily_gain
from btc_skill_rebuild.research_execution_drift_v7r6 import examples,STEP
from btc_skill_rebuild.research_walkforward_barriers_v7r6 import FOLDS,UTC

RISK_INDICES=GROUPS['volatility_activity_only']
SIGNAL_INDICES=GROUPS['signed_flow_only']
HORIZONS={'1h':(12,.007),'4h':(48,.012)}


def masked_flow(x):
    return tuple(v if i in SIGNAL_INDICES else 0. for i,v in enumerate(x))


def split_prob(event_p,flow_model,x,alpha):
    # Preserve TOTAL probability of first touch and of each non-event class.
    up_cond=direction_up(flow_model,masked_flow(x),alpha)
    risk=event_p[0]+event_p[1]
    adjusted=[risk*up_cond,risk*(1-up_cond),event_p[2],event_p[3]]
    if not all(math.isfinite(v) and 0<=v<=1 for v in adjusted) or abs(sum(adjusted)-1)>1e-10:
        raise ValueError('invalid risk-preserving v7R6 conditional math')
    return adjusted


def score(sample,risk_model,flow_model,risk_shrink,alpha):
    rows=[]
    for t,x,y in sample:
        base=prob(risk_model,tuple(x[i] for i in RISK_INDICES),risk_shrink)
        improved=split_prob(base,flow_model,x,alpha)
        rows.append((t,y,base,improved))
    return rows


def compare(rows):
    proper=[(t,brier(base,y)-brier(new,y)) for t,y,base,new in rows]
    directional=[(t,directional_loss(base,y)-directional_loss(new,y))
                 for t,y,base,new in rows if y in (0,1)]
    return {'n_due':len(rows),'n_directional_first_touch_due':len(directional),
            'mean_incremental_multiclass_Brier':statistics.mean(z for t,z in proper),
            'all_due_daily':daily_gain(proper),
            'directional_due_daily':daily_gain(directional) if directional else None,
            'same_future_observation_for_both':True,
            'same_event_risk_for_both':True}


def evaluate(rows):
    all_examples=examples(rows)
    outcome={}
    for h,(steps,barrier) in HORIZONS.items():
        all_slots=[]
        for i,t,x,close,log in all_examples:
            if t%(15*60000) or i+steps>=len(rows):continue
            matured=int(rows[i+steps][0])+STEP
            first,touch=labels(rows,i,steps,barrier)
            all_slots.append((t,matured,x,first))
        trials=[]
        for start in FOLDS:
            first=int(start.timestamp()*1000);last=first+7*86400000
            v_begin=first-8*86400000;v_end=first-86400000
            tr=[(t,x,y) for t,due,x,y in all_slots if due<v_begin]
            val=[(t,x,y) for t,due,x,y in all_slots if v_begin<=t and due<v_end]
            te=[(t,x,y) for t,due,x,y in all_slots if first<=t<last]
            if min(len(tr),len(val),len(te))<300:raise ValueError('missing complete fixed-grid sample')
            risk_train=[(t,tuple(x[i] for i in RISK_INDICES),y,None) for t,x,y in tr]
            risk_model=fit(risk_train)
            risk_shrink=min(SHRINK,key=lambda z:statistics.mean(
                brier(prob(risk_model,tuple(x[j] for j in RISK_INDICES),z),y)
                for t,x,y in val))
            flow_model=train_direction([(t,masked_flow(x),y) for t,x,y in tr])
            alpha=min(SHRINK,key=lambda z:statistics.mean(
                brier(new,y) for t,y,base,new in score(val,risk_model,flow_model,risk_shrink,z)))
            vals=score(val,risk_model,flow_model,risk_shrink,alpha)
            all_te=score(te,risk_model,flow_model,risk_shrink,alpha)
            fixed=[item for item in all_te if item[0]%(steps*STEP)==0]
            summary=compare(fixed)
            zero=compare([(t,y,b,b) for t,y,b,n in fixed])
            trials.append({'week_start_utc':start.isoformat(),
              'fixed_grid_spacing_minutes':steps*5,
              'risk_shrink_chosen_from_previous_validation':risk_shrink,
              'direction_shrink_chosen_from_previous_validation':alpha,
              'validation_sample':compare(vals),
              'fixed_nonoverlap_outcome':summary,
              'full_overlapping_diagnostic_not_effective_sample':compare(all_te),
              'risk_only_constant_direction_reference':zero})
            print('SPLIT_RISK_DIRECTION',h,start.date(),
                  'validation_dir_alpha',alpha,
                  'nonoverlap_due',summary['n_due'],
                  'nonoverlap_event_due',summary['n_directional_first_touch_due'],
                  'incremental_Brier',round(summary['mean_incremental_multiclass_Brier'],7),
                  'dir_increment',round(summary['directional_due_daily']['mean_daily_gain'],7) if summary['directional_due_daily'] else None,
                  flush=True)
        outcome[h]={'folds':trials,'positive_nonoverlapping_Brier_weeks':sum(
            f['fixed_nonoverlap_outcome']['mean_incremental_multiclass_Brier']>0 for f in trials)}
    return {'schema':'btc-v7r6-preserved-risk-conditional-direction-v1',
        'this_is_one_existing_v7r6_mathematical_head_not_production':True,
        'retrospective_known_history':True,'no_trading_authority':True,
        'strictly_identical_risk_and_outcomes_in_paired_comparison':True,
        'frozen_feature_indices_risk':RISK_INDICES,'frozen_feature_indices_flow':SIGNAL_INDICES,
        'outcomes':outcome}


def run(raw,out):
    with gzip.open(raw,'rt') as f:rows=json.load(f)
    res=evaluate(rows)
    res['historical_source_SHA256']=hashlib.sha256(pathlib.Path(raw).read_bytes()).hexdigest()
    pathlib.Path(out).write_text(json.dumps(res,indent=2,sort_keys=True,allow_nan=False)+'\n')
    for h,s in res['outcomes'].items():
        print('RISK_DIRECTION_SPLIT_SUMMARY',h,s['positive_nonoverlapping_Brier_weeks'],'positive of',len(s['folds']),flush=True)
    return res

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--raw',required=True);p.add_argument('--out',required=True)
    x=p.parse_args();run(x.raw,x.out)
