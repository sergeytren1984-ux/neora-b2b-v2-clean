"""Causal R6/calendar input assembly, prior to full-candidate calculation.

Calendar counts describe the received BLS schedule only. They are not DXY,
Nasdaq futures, released macro values or surprises. Missing inputs stay None.
Actual signed R6 inputs are not a calibrated R6 alert or a trained coefficient.
"""
import datetime as dt
import json
import pathlib
import numpy as np
from calendar_ingest import parse
from r6_factor_adapter import extract,NAMES,SOURCE_SHA
from forecast import feature as spot_feature
from macro_quote_adapter import MARKET_NAMES

UTC=dt.timezone.utc
BLS_SOURCE='https://www.bls.gov/schedule/news_release/bls.ics'
CALENDAR_NAMES=tuple('bls_scheduled_events_next_'+str(h)+'h' for h in (1,4,24))
SPOT_NAMES=tuple('spot_'+period+'_'+kind for period in ('15m','1h','4h','24h') for kind in ('log_return','realized_volatility','signed_taker_fraction','path_efficiency'))+('spot_1h_volume_vs_4h_quarter','spot_distance_4h_high','spot_distance_4h_low','UTC_hour_sine','UTC_hour_cosine')
FEATURE_NAMES=SPOT_NAMES+NAMES+MARKET_NAMES+CALENDAR_NAMES

def stamp(s):
    t=dt.datetime.fromisoformat(s.replace('Z','+00:00'))
    if t.tzinfo is None:raise ValueError('timezone required')
    return t.astimezone(UTC)

def calendar_features(raw,receipt,asof):
    if receipt['source']!=BLS_SOURCE:raise ValueError('calendar source mismatch')
    events=parse(raw,receipt);at=stamp(asof);received=stamp(receipt['received_at_utc'])
    if at<received:return {'available':False,'status':'NOT_YET_RECEIVED','values':None,'vintage_sha256':receipt['sha256']}
    # Zero is an actual count of no listed events, never a filled missing value.
    known=[stamp(e['release_utc']) for e in events if e['schedule_known_before_release']]
    values={name:sum(at<t<=at+dt.timedelta(hours=h) for t in known) for name,h in zip(CALENDAR_NAMES,(1,4,24))}
    return {'available':True,'status':'RECEIVED_BLS_SCHEDULE_ONLY','values':values,
        'received_at_utc':received.isoformat(),'vintage_sha256':receipt['sha256'],
        'historical_availability_before_receipt':False,'independent_receipt_timestamp_verified':False,
        'covers_all_required_macro_events':False,'numeric_macro_surprise_available':False,
        'DXY_or_Nasdaq_futures_or_live_10y_quote':False}

def assemble(record_path,verifier,calendar_raw,calendar_receipt,source_sha=SOURCE_SHA,market=None,issued_at=None):
    r6=extract(record_path,verifier,source_sha)
    if not r6['available']:
        return {'eligible_for_research_matrix':False,'features':None,'R6':r6,'macro':None,
            'reasons':['R6_INPUT_UNAVAILABLE'],'full_system_ready':False,'trading_authority':False}
    # Observation cannot be used at its candle anchor before its HTTP receipt.
    first=max(stamp(r6['input_received_at_utc']),stamp(r6['signed_record_available_not_before_utc']))
    at=first if issued_at is None else stamp(issued_at)
    if market and market.get('available'):
        at=max(at,stamp(market['available_at_utc']))
    asof=at.isoformat()
    macro=calendar_features(calendar_raw,calendar_receipt,asof)
    reasons=[]
    if not macro['available']:reasons.append('CALENDAR_NOT_YET_RECEIVED')
    if not market or not market.get('available'):reasons.extend((market or {}).get('reasons',['VERIFIED_MACRO_QUOTES_UNAVAILABLE']))
    ready=not reasons;values=None
    # The R6 extractor has already authenticated and rederived these raw rows.
    record=json.loads(pathlib.Path(record_path).read_bytes())
    observed=record['snapshot']['observation']
    if at-first>dt.timedelta(minutes=10) or at-stamp(r6['anchor_utc'])>dt.timedelta(minutes=12):reasons.append('INTEGRATED_INPUT_DEADLINE_EXCEEDED')
    book_ms=int(observed['book']['vendor_timestamp_ms'])
    if not 0<=at.timestamp()*1000-book_ms<=60000:reasons.append('R6_BOOK_STALE_AT_COMBINED_AVAILABILITY')
    micro_ms=int(observed['microflow']['vendor_close_ms'])
    if not 0<=at.timestamp()*1000-micro_ms<=120000:reasons.append('R6_MICROFLOW_STALE_AT_COMBINED_AVAILABILITY')
    ready=not reasons
    raw=record['snapshot']['five_min_rows']
    a=np.array([[float(row[k]) for k in (0,1,2,3,4,5,6,8,9)] for row in raw])
    anchor=int(stamp(r6['anchor_utc']).timestamp()*1000)
    if len(a)<289 or not np.all(np.diff(a[:,0])==300000) or a[-1,6]+1!=anchor:raise ValueError('spot features require exact closed history')
    spot,sigma=spot_feature(a,len(a)-1,anchor)
    if ready:
        if tuple(market['feature_names'])!=MARKET_NAMES:raise ValueError('wrong macro quote schema')
        values=spot.tolist()+[r6['values'][name] for name in NAMES]+market['features']+[macro['values'][name] for name in CALENDAR_NAMES]
        if not np.isfinite(values).all():raise ValueError('nonfinite causal numeric input')
    return {'schema':'btc-r6-bls-causal-input-row-v1','anchor_utc':r6['anchor_utc'],'features_available_at_utc':asof,
        'feature_names':list(FEATURE_NAMES),'features':values,'eligible_for_research_matrix':ready,
        'reference_spot':float(a[-1,4]),'past_sigma':sigma,
        'R6':r6,'macro':macro,'macro_quotes':market,'reasons':reasons,
        'R6_numeric_inputs_assembled':True,'R6_state_or_alert_assembled':False,
        'numeric_input_assembly_is_not_a_trained_forecast':True,
        'full_system_ready':False,'trading_authority':False}

def calculation_gate(model,inputs,execution=None,evaluated_at=None):
    """Check dependencies before a forecast or buy/wait callable is invoked."""
    reasons=list(inputs.get('reasons',[]))
    at=dt.datetime.now(UTC) if evaluated_at is None else stamp(evaluated_at)
    r6=inputs.get('R6') or {}
    for key,limit in (('book_observed_at_utc',60),('microflow_closed_at_utc',120)):
        try:
            age=(at-stamp(r6[key])).total_seconds()
            if not 0<=age<=limit:reasons.append('R6_STALE_OR_FUTURE_AT_CALCULATION:'+key)
        except (KeyError,ValueError,TypeError):reasons.append('R6_CURRENT_TIMESTAMP_UNAVAILABLE:'+key)
    try:
        if stamp(inputs['features_available_at_utc'])>at:reasons.append('INPUTS_NOT_YET_AVAILABLE_AT_CALCULATION')
    except (KeyError,ValueError,TypeError):reasons.append('COMBINED_AVAILABILITY_TIMESTAMP_UNAVAILABLE')
    if not inputs.get('eligible_for_research_matrix'):reasons.append('CAUSAL_FACTOR_ROW_UNAVAILABLE')
    if tuple(model.get('integrated_feature_names',()))!=FEATURE_NAMES:reasons.append('MODEL_NOT_FITTED_WITH_R6_AND_CALENDAR_SCHEMA')
    if model.get('paired_causal_factor_training_verified') is not True:reasons.append('PAIRED_FACTOR_TRAINING_NOT_VERIFIED')
    macro=inputs.get('macro') or {}
    if (inputs.get('macro_quotes') or {}).get('immutable_collector_source_proven') is not True:reasons.append('MACRO_COLLECTOR_RUNTIME_NOT_PINNED')
    if macro.get('covers_all_required_macro_events') is not True:reasons.append('REQUIRED_MACRO_EVENT_COVERAGE_NOT_VERIFIED')
    direction=list(dict.fromkeys(reasons));entry=list(direction)
    if not execution or execution.get('actual_operator_terms_verified') is not True:entry.append('ACTUAL_OPERATOR_EXECUTION_NOT_VERIFIED')
    return {'direction':{'allowed':not direction,'reasons':direction},
        'buy_or_wait':{'allowed':not entry,'reasons':entry},'full_system_ready':False,'trading_authority':False}

def guarded_calculate(model,inputs,predict,execution=None):
    gate=calculation_gate(model,inputs,execution)
    out={'schema':'btc-full-candidate-precalculation-contract-v1','anchor_utc':inputs.get('anchor_utc'),
        'dependency_checks':gate,'forecast':None,'entry':None,'full_system_ready':False,'trading_authority':False}
    # No numbers and no BUY/WAIT hypothesis are manufactured for missing inputs.
    if not gate['direction']['allowed']:out['status']='BLOCKED_BEFORE_CALCULATION';return out
    result=predict(model,inputs)
    out['forecast']=result['forecast']
    if gate['buy_or_wait']['allowed']:out['entry']=result.get('entry')
    out['status']='RESEARCH_CALCULATION_ONLY';return out

def audit_directory(root,calendar_root,verifier,markets=None):
    cal=pathlib.Path(calendar_root);raw=(cal/'bls.ics').read_bytes();receipt=json.loads((cal/'receipt.json').read_text())
    rows=[];failures=[]
    for path in sorted(pathlib.Path(root).glob('*/record.json')):
        try:
            anchor=json.loads(path.read_bytes()).get('anchor_utc')
            rows.append(assemble(path,verifier,raw,receipt,market=(markets or {}).get(anchor)))
        except Exception as e:failures.append({'slot':path.parent.name,'error':type(e).__name__,'message':str(e)})
    return {'schema':'btc-first-plan-factor-readiness-audit-v1','rows':rows,'rejected_records':failures,
        'research_eligible_rows':sum(r['eligible_for_research_matrix'] for r in rows),
        'full_candidate_training_ready':False,'first_step_trading_readiness_proven':False,
        'historical_macro_proxy_rows_admitted':0,'historical_R6_book_rows_invented':0,
        'full_system_ready':False,'trading_authority':False}
