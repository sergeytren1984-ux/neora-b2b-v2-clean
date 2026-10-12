"""BTC v7R6 pairwise prospective QUALITY MATH of two directional policies.

Consumes EXACTLY the same independent resolved source-slot labels and the
same full due grid. Enforces exact own-slot matching and minute-open lead
through existing episode_quality_v4.report. Never authenticates supplied
proofs, never labels an assumed historical public timestamp as verified.
Does not modify frozen R5/R6 or issue new price predictions/trade orders.
"""
from __future__ import annotations
from btc_demand_v7.episode_quality_v4 import report,episodes_from_verified_barriers
from btc_demand_v7.prospective_core import when
from datetime import timedelta


def paired_source_signal_score(horizon, full_due_count,missing_due,
                               resolved_outcomes, original_alerts, proposed_alerts,
                               *, registered_due_slots):
    if horizon not in ('1h','4h'):
        raise ValueError('invalid signed barrier forecast horizon')
    if not isinstance(missing_due,int) or not 0<=missing_due<=full_due_count:
        raise ValueError('invalid missing due denominator')
    if not isinstance(full_due_count,int) or full_due_count<0:
        raise ValueError('invalid predeclared fixed grid')
    if len(resolved_outcomes)+missing_due!=full_due_count:
        raise ValueError('missing resolved NEITHER/ambiguous due windows')
    # Never trust aggregate due_count or arbitrary submitted alert IDs to
    # stand in for the actual preregistered schedule. Require a complete
    # external registry of exact mature slots with their own UTC deadlines.
    # This is mathematical binding, NOT cryptographic verification of
    # signatures or Rekor inclusion (performed separately).
    if not isinstance(registered_due_slots,(tuple,list)) or len(registered_due_slots)!=full_due_count:
        raise ValueError('missing exact predeclared due slot registry')
    grid={}
    previous=None
    for item in registered_due_slots:
        sid=item['slot_id']
        slot=when(item['slot_utc'])
        deadline=when(item['forecast_deadline_utc'])
        if not isinstance(sid,str) or not sid or sid in grid:
            raise ValueError('duplicate or empty registered slot id')
        if not slot<=deadline<=slot+timedelta(minutes=13):
            raise ValueError('publication deadline outside registered 13m budget')
        if previous is not None and slot-previous!=timedelta(minutes=15):
            raise ValueError('predeclared 15min due grid is not contiguous')
        if sid!=slot.strftime('%Y%m%dT%H%MZ'):
            raise ValueError('slot id cannot disagree with frozen UTC clock')
        previous=slot
        grid[sid]=(slot,deadline)
    outcome_ids={x['slot_id'] for x in resolved_outcomes}
    if not outcome_ids.issubset(grid):
        raise ValueError('outcomes are not drawn from the registered UTC grid')
    if len(grid)-len(outcome_ids)!=missing_due:
        raise ValueError('missing due slots cannot be replaced by favorable outcomes')
    horizon_minutes=60 if horizon=='1h' else 240
    for item in resolved_outcomes:
        side=item['direction']
        if side in ('UP_FIRST','DOWN_FIRST'):
            slot=grid[item['slot_id']][0]
            touched=when(item['touch_open_utc'])
            if not slot<=touched<slot+timedelta(minutes=horizon_minutes):
                raise ValueError('first touch is outside its own registered horizon')
    reference={x['slot_id']:x for x in resolved_outcomes}
    if len(reference)!=len(resolved_outcomes):
        raise ValueError('duplicate future-label source slot')
    def normalize_alerts(rows):
        out=[];seen=set()
        for a in rows:
            if a['slot_id'] in seen:
                raise ValueError('replayed alert cannot be counted twice')
            seen.add(a['slot_id'])
            if a['side'] not in ('UP_FIRST','DOWN_FIRST'):
                raise ValueError('unknown directional alert')
            if a.get('eligible') is not True:
                raise ValueError('only real delivered alerts belong in alarm denominator')
            if not a.get('public_delivery_utc'):
                raise ValueError('missing as-of public delivery time')
            if a['slot_id'] not in grid:
                raise ValueError('public alert cannot have an unregistered source slot')
            public=when(a['public_delivery_utc'])
            slot,deadline=grid[a['slot_id']]
            if not slot<=public<=deadline:
                raise ValueError('public alert outside the original issue slot deadline')
            out.append(a)
        return out
    old=normalize_alerts(original_alerts)
    new=normalize_alerts(proposed_alerts)
    first=report(horizon,resolved_outcomes,old,
                 full_due_count=full_due_count,missing_or_late_count=missing_due)
    second=report(horizon,resolved_outcomes,new,
                 full_due_count=full_due_count,missing_or_late_count=missing_due)
    horizons={}
    for lead in (10,30,60):
        k=str(lead)
        baseline=first['conservative_lead_minutes'][k]
        candidate=second['conservative_lead_minutes'][k]
        horizons[k]={
            'baseline_episodes_own_slot_correct':baseline['verified_distinct_episodes_matched'],
            'candidate_episodes_own_slot_correct':candidate['verified_distinct_episodes_matched'],
            'added_episodes_correct_candidate_minus_baseline':(
                candidate['verified_distinct_episodes_matched']-baseline['verified_distinct_episodes_matched']),
            'baseline_correct_public_alerts':baseline['verified_alerts_matched'],
            'candidate_correct_public_alerts':candidate['verified_alerts_matched'],
            'baseline_alerts_not_own_slot_correct':baseline['verified_alerts_without_matching_episode'],
            'candidate_alerts_not_own_slot_correct':candidate['verified_alerts_without_matching_episode'],
            'baseline_alert_precision':baseline['observed_alert_precision'],
            'candidate_alert_precision':candidate['observed_alert_precision'],
            'baseline_episode_recall':baseline['observed_episode_recall'],
            'candidate_episode_recall':candidate['observed_episode_recall'],
        }
    return {'schema':'btc-v7r6-one-grid-independent-source-consensus-episode-research-v1',
      'horizon':horizon,'full_due_count':full_due_count,
      'resolved_due':len(resolved_outcomes),'missing_due':missing_due,
      'unique_resolved_episodes':first['n_verified_nonoverlapping_episodes'],
      'original_published_alerts_count_claimed':len(old),
      'candidate_published_alerts_count_claimed':len(new),
      'same_outcome_and_missing_due_grid_for_both':True,
      'exact_registered_slot_ids_and_public_deadlines_verified_mathematically':True,
      'no_cross_slot_first_touch_credit':True,
      'lead_minutes':horizons,
      'n_days_of_independent_prospective_publication_verified_by_this_math_module':0,
      'signed_rekor_proofs_verified_by_this_math_module':False,
      'not_statistical_predictive_skill_proof':True,
      'trading_authority':False}
