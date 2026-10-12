"""Research-only paired future-outcome evaluator. Strictly shared R6 publication time.

The caller MUST independently verify (1) R6 signed pre-event signal, (2)
GitHub Actions completed job and its commit holding exact JSON, (3) signed
future vendor 1m raw obtained AFTER maturity. Neither the source JSON nor
its recorded compute timestamp is accepted as a public delivery proof.
The evaluator has no role in model production or placing OTC orders.
"""
from __future__ import annotations
from datetime import datetime,timedelta,timezone
import math
from btc_demand_v7.event_semantics import first_passage,BARRIERS
from btc_demand_v7.shadow_contract_v3 import future_anchor
from btc_demand_v7.prospective_core import when
from btc_demand_v7.demand_change_v2 import source_hash
from btc_demand_v7.v7r6_live_pair_worker import START,END,R5_SHA,R6_SHA,sha

PINNED_RUNNER_SHA="a68632de49b1afb5a4d1b614b28fdef76f769e96"
MAX_PUBLIC_MINUTES=13
SCORE_GRACE=35

def _side(d):
    if not isinstance(d,dict):raise ValueError('not a signed diagnostic')
    side=d.get('warning_side') if d.get('alert') is True else None
    if side not in (None,'UP','DOWN'):raise ValueError('invalid signed alert side')
    if d.get('alert') is True and side is None:raise ValueError('directionless public alert')
    return {'UP':'UP_FIRST','DOWN':'DOWN_FIRST',None:None}[side]

def one_pair(shadow,proof,reference,raw_rows,head,*,observed_utc,as_of_utc):
    """Evaluate both candidates against EXACTLY ONE independently observed future.

    proof must originate from an authenticated GitHub API job-completion
    verification and a Git commit binding the signed R6 event. No assertions
    of such authentication arise solely from passing proof as a dict.
    """
    if head not in ('1h','4h'):raise ValueError('unknown registered barrier horizon')
    if shadow.get('schema')!='btc-v7r6-paired-future-public-shadow-v1' or shadow.get('kind')!='R6_SIGNED_SHADOW':
        raise ValueError('not a signed prospective R6 comparison')
    if (shadow.get('research_model_sha')!=R6_SHA or shadow.get('runner_sha')!=PINNED_RUNNER_SHA
        or shadow.get('trading_authority') is not False):
        raise ValueError('wrong frozen model or unapproved trade rights')
    slot=when(shadow['anchor_utc'])
    if not START<=slot<END or slot.minute%15 or slot.second or slot.microsecond:
        raise ValueError('unregistered slot')
    if shadow['slot_id']!=slot.strftime('%Y%m%dT%H%MZ'):
        raise ValueError('foreign/aliased signed comparison')
    if (shadow['baseline_r5_diagnostic']['current_snapshot_sha256']
        !=shadow['challenger_diagnostic']['current_snapshot_sha256']
        or shadow['source_r5_snapshot_sha256']!=shadow['challenger_diagnostic']['current_snapshot_sha256']):
        raise ValueError('contenders do not see identical signed market information')
    if (proof.get('status')!='VERIFIED_GITHUB_COMPLETED_JOB_AND_SIGNED_COMMIT'
        or proof.get('conclusion')!='success'
        or proof.get('job_source_sha')!=PINNED_RUNNER_SHA):
        raise ValueError('not an independently verified GitHub public release')
    if proof.get('signed_shadow_sha256')!=sha(shadow):
        raise ValueError('Git public release not bound to exact signed decision')
    if not isinstance(proof.get('run_id'),int) or proof['run_id']<=0:
        raise ValueError('missing immutable workflow run reference')
    published=when(proof['job_completed_utc'])
    computed=when(shadow['decision_computed_utc'])
    if not computed<=published or computed<slot:
        raise ValueError('noncausal model publication order')
    if published>slot+timedelta(minutes=MAX_PUBLIC_MINUTES):
        raise ValueError('late GitHub release cannot claim timely public signal')
    observed=when(observed_utc);now=when(as_of_utc)
    due=future_anchor(published)+timedelta(minutes=BARRIERS[head][0])
    if observed<due or now<observed:
        raise ValueError('forward bars collected before their actual future maturity')
    if int(reference[0])+60000!=int(reference[6])+1:
        raise ValueError('invalid reference minute length')
    minute_floor=(int(published.timestamp()*1000)//60000)*60000
    if int(reference[6])+1!=minute_floor:
        raise ValueError('reference price not adjacent to release')
    o,h,l,c=map(float,reference[1:5])
    if not(all(math.isfinite(x) for x in (o,h,l,c)) and 0<l<=min(o,c)<=max(o,c)<=h):
        raise ValueError('invalid source reference OHLC')
    result=first_passage(future_anchor(published),c,raw_rows,head)
    touch=when(result['first_barrier_touch_utc'])-timedelta(minutes=1) if result['first_barrier_touch_utc'] else None
    lead=((touch-published).total_seconds()/60 if touch else None)
    policies={}
    for policy,key in (('frozen_v7r5','baseline_r5_diagnostic'),('consensus_v7r6','challenger_diagnostic')):
        predicted=_side(shadow[key]);triggered=predicted is not None
        matched=(triggered and predicted==result['direction'] and result['direction'] in ('UP_FIRST','DOWN_FIRST'))
        policies[policy]={
            'issued':triggered,'side':predicted,
            'correct_first_touch':bool(matched),
            'correct_with_10m_lead':bool(matched and lead is not None and lead>=10),
            'correct_with_30m_lead':bool(matched and lead is not None and lead>=30),
            'correct_with_60m_lead':bool(matched and lead is not None and lead>=60),
            'false_or_insufficient_60m':bool(triggered and not (matched and lead is not None and lead>=60))}
    return {'schema':'btc-v7r6-causal-paired-prospective-outcome-v1',
            'slot_id':shadow['slot_id'],'horizon':head,
            'model_sha':R6_SHA,'frozen_comparator_sha':R5_SHA,
            'public_release_proof_run_id':proof['run_id'],
            'publication_utc':published.isoformat(),
            'reference_price':c,'upper':result['upper'],'lower':result['lower'],
            'event_result':result['direction'],
            'event_conservative_first_touch_lead_minutes':lead,
            'same_forward_reference_for_both_models':True,
            'candidate_stats':policies,
            'trading_authority':False,'actual_OTC_fill_observed':False}

def fixed_grid_score(events,*,horizon,as_of_utc):
    """Strict registered horizon denominator; missing never magically disappears.

    Full 7-day fixed grid starts after 32 warmup slots. Fixed conservative
    due cutoff is 13m public bound + event horizon + 35m outcome grace.
    """
    if horizon not in ('1h','4h'):raise ValueError('unknown horizon')
    now=when(as_of_utc)
    unique={}
    for e in events:
        if e.get('horizon')!=horizon:raise ValueError('mixed future horizon labels')
        sid=e['slot_id']
        if sid in unique:raise ValueError('duplicate signed score or substituted outcome')
        unique[sid]=e
    due_count=0;included=[]
    for i in range(32,7*96):
        slot=START+timedelta(minutes=15*i)
        due=slot+timedelta(minutes=MAX_PUBLIC_MINUTES+BARRIERS[horizon][0]+SCORE_GRACE)
        sid=slot.strftime('%Y%m%dT%H%MZ')
        if now<due:
            if sid in unique:raise ValueError('premature scored outcome without due')
            continue
        due_count+=1
        if sid in unique:included.append(unique.pop(sid))
    if unique:raise ValueError('outcome not in registered eligible matured grid')
    results={}
    for policy in ('frozen_v7r5','consensus_v7r6'):
        num_alert=sum(e['candidate_stats'][policy]['issued'] is True for e in included)
        ok=sum(e['candidate_stats'][policy]['correct_with_60m_lead'] is True for e in included)
        failed=sum(e['candidate_stats'][policy]['false_or_insufficient_60m'] is True for e in included)
        results[policy]={
            'alerts_on_resolved':num_alert,'correct_with_60m_lead':ok,
            'false_or_insufficient_60m':failed,
            'observed_alert_precision':ok/num_alert if num_alert else None}
    return {'schema':'btc-v7r6-full-due-paired-score-v1',
            'horizon':horizon,'matured_registered_due':due_count,
            'independently_verified_resolved':len(included),
            'missing_due_including_missing_signals':due_count-len(included),
            'missing_blocks_trading':due_count!=len(included),
            'comparison':results,
            'economic_OTC_advantage_proven':False,
            'trade_skill_proven':False,'trading_authority':False}
