"""Unified research outputs and a fail-closed full-system action contract.

Base forecasts, R6 diagnostics, macro provenance and actual operator execution
remain distinct. Missing validated contribution is never silently labelled used.
"""
import datetime as dt
import numpy as np
import joint_candidate as joint
import forecast as f
import walkforward as w

def summarize(model,x,sigma,spot,anchor,budget,premium):
    c,h,l,weights=joint.paths(model,np.asarray(x),sigma)
    result={'schema':'btc-unified-candidate-research-output-v1','anchor_utc':anchor,
        'scope':'price, direction, competing barriers and hypothetical delayed entry from one joint distribution',
        'trading_authority':False,'full_system_ready':False,'prospective_skill_proven':False,
        'forecast':{},'entry':{},'barriers':{}}
    for hours in (1,4,24):
        prices=spot*np.exp(c[:,hours-1]);q=joint.weighted_quantile(prices,weights,[.1,.5,.9])
        classes=w.endpoint_classes(c,hours);p=np.bincount(classes,weights=weights,minlength=3)
        result['forecast'][str(hours)]={'медиана':float(q[1]),'квантиль_10':float(q[0]),'квантиль_90':float(q[2]),
            'вероятность_существенного_роста':float(p[0]),'вероятность_существенного_снижения':float(p[1]),'вероятность_малого_изменения':float(p[2]),
            'вероятности_подтверждены_перспективно':False}
        expected=joint.entry(c,weights,spot,hours,budget,premium)
        expected['исследовательская_гипотеза']='ПОДОЖДАТЬ' if expected['expected_extra_btc']>0 else 'КУПИТЬ_СЕЙЧАС'
        expected['hypothesis_not_trade_recommendation']=True;result['entry'][str(hours)]=expected
    for hours in (24,48,72):
        classes=f.first_passage(h,l,hours=hours);result['barriers'][str(hours)]=(np.bincount(classes,weights=weights,minlength=4)).tolist()
    result['execution_assumptions']={'budget_usdt':budget,'buy_premium_usdt_per_btc':premium,'delay_from_closed_anchor_hours':1,
        'hypothetical':True,'rejections_and_partial_fills_in_model':False}
    return result

REQUIREMENTS=('predictive_advantage_on_unknown_outcomes','probabilities_calibrated_prospectively',
    'R6_contribution_checked','macro_contribution_checked','macro_current_vintages_verified',
    'actual_operator_delay_cost_and_rejections_checked','public_release_before_outcomes_verified',
    'complete_decision_grid_checked')

def admission(evidence,current_inputs):
    missing=[name for name in REQUIREMENTS if evidence.get(name) is not True]
    # Current availability and meaningful numeric use both must be explicit.
    for name in ('spot_fresh','R6_verified_and_fresh','macro_required_inputs_verified_and_fresh','actual_operator_quote_current'):
        if current_inputs.get(name) is not True:missing.append(name)
    if current_inputs.get('rapid_unmodelled_move_observed') is True:missing.append('rapid_unmodelled_move_requires_new_validated_assessment')
    return {'full_system_ready':not missing,'trade_decision_allowed':not missing,
        'decision':'BLOCKED' if missing else 'ADMITTED_TO_DECISION_SUPPORT_ONLY',
        'missing_requirements':missing,'automated_trade_execution_allowed':False}

def attach_context(output,evidence,current_inputs,r6=None,macro=None):
    gate=admission(evidence,current_inputs)
    result=dict(output);result['full_system_admission']=gate
    result['R6_context']=r6;result['macro_context']=macro
    result['R6_numeric_contribution_admitted']=evidence.get('R6_contribution_checked') is True
    result['macro_numeric_contribution_admitted']=evidence.get('macro_contribution_checked') is True
    # Never flip readiness on a research output merely from receipt booleans.
    result['full_system_ready']=False;result['trading_authority']=False
    result['actual_action']='BLOCKED_RESEARCH_OUTPUT'
    return result
