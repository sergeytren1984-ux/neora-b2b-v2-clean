"""Attach only closed observed targets to causally assembled input rows."""
import datetime as dt,hashlib,json
import numpy as np
from factor_integration import stamp

def targets(inputs,rows,cutoff_utc):
    cutoff=int(stamp(cutoff_utc).timestamp()*1000);prices={}
    for i,row in enumerate(rows):
        start=int(row[0]);end=int(row[6])+1
        if end-start!=300000 or end>cutoff:raise ValueError('unclosed or malformed target candle')
        if i and start!=int(rows[i-1][6])+1:raise ValueError('target candle grid gap')
        op,hi,lo,cl=map(float,row[1:5])
        if not np.isfinite([op,hi,lo,cl]).all() or not 0<lo<=min(op,cl)<=max(op,cl)<=hi:raise ValueError('invalid target OHLC')
        if end in prices:raise ValueError('duplicate target candle')
        prices[end]=cl
    out=[]
    for sample in inputs:
        r=dict(sample);anchor=int(stamp(r['anchor_utc']).timestamp()*1000);spot=r.get('reference_spot')
        r['direction_targets']={};r['delayed_entry_spot_proxy_targets']={}
        for h in (1,4,24):
            end=anchor+h*3600000;actual=prices.get(end) if end<=cutoff else None
            r['direction_targets'][str(h)]=None if actual is None or spot is None else {'end_utc':dt.datetime.fromtimestamp(end/1000,dt.timezone.utc).isoformat(),
                'actual_close':actual,'log_return':float(np.log(actual/spot)),'positive_return':bool(actual>spot)}
            buy=prices.get(anchor+3600000);wait=prices.get(anchor+(h+1)*3600000)
            r['delayed_entry_spot_proxy_targets'][str(h)]=None if buy is None or wait is None else {
                'buy_after_one_hour_spot':buy,'wait_then_one_hour_spot':wait,'log_price_difference':float(np.log(wait/buy)),
                'actual_operator_execution':False,'commissions_and_rejections_verified':False}
        r['future_targets_never_filled']=True;r['training_target_is_not_prospective_forecast_evidence']=True;out.append(r)
    return out

def training_readiness(rows):
    eligible=[r for r in rows if r.get('eligible_for_research_matrix')]
    count={str(h):sum(r['direction_targets'][str(h)] is not None for r in eligible) for h in (1,4,24)}
    reasons=[]
    if not eligible:reasons.append('NO_COMPLETE_CAUSAL_INPUT_ROWS')
    for h,n in count.items():
        labels=[r['direction_targets'][h]['positive_return'] for r in eligible if r['direction_targets'][h] is not None]
        if not labels:reasons.append('NO_CLOSED_DIRECTION_TARGETS:'+h+'h')
        elif len(set(labels))<2:reasons.append('BOTH_DIRECTION_CLASSES_NOT_OBSERVED:'+h+'h')
    if not all((r.get('macro_quotes') or {}).get('immutable_collector_source_proven') for r in eligible):reasons.append('LEGACY_MACRO_RUNTIME_UNPINNED')
    if len(eligible)<480:reasons.append('INSUFFICIENT_ROWS_FOR_TWO_240_ROW_SPLITS')
    if not eligible or not all(r.get('complete_72h_actual_target') is True for r in eligible):reasons.append('COMPLETE_OBSERVED_72H_TRAJECTORIES_NOT_VERIFIED')
    return {'eligible_inputs':len(eligible),'closed_direction_targets':count,'can_begin_full_candidate_training':not reasons,
        'reasons':reasons,'trading_authority':False,'full_system_ready':False}

def trajectory_matrix(inputs,candles,cutoff_utc):
    """Build observed 72h targets for the fixed candidate, never extrapolate.

    Returned rows still require chronological splitting and source qualification
    in fit_verified. This function grants no forecast or trading admission.
    """
    from factor_integration import FEATURE_NAMES
    cutoff=int(stamp(cutoff_utc).timestamp()*1000);bars={}
    for bar in candles:
        start=int(bar[0]);end=int(bar[6])+1
        op,hi,lo,cl=map(float,bar[1:5])
        if end-start!=300000 or end>cutoff or not np.isfinite([op,hi,lo,cl]).all() or not 0<lo<=min(op,cl)<=max(op,cl)<=hi:raise ValueError('invalid or unclosed trajectory candle')
        if start in bars:raise ValueError('duplicate trajectory candle')
        bars[start]=(hi,lo,cl)
    selected=[];rejected=[];arrays={k:[] for k in ('x','anchors','scales','spot','close','high','low')}
    for row in inputs:
        at=int(stamp(row['anchor_utc']).timestamp()*1000)
        reason=None
        if not row.get('eligible_for_research_matrix'):reason='REQUIRED_FACTOR_ROW_UNAVAILABLE'
        elif tuple(row.get('feature_names',()))!=FEATURE_NAMES:raise ValueError('wrong trajectory feature schema')
        elif at+72*3600000>cutoff:reason='72H_TARGET_NOT_CLOSED'
        else:
            starts=range(at,at+72*3600000,300000)
            if any(t not in bars for t in starts):reason='ACTUAL_TRAJECTORY_GAP'
        if reason:
            rejected.append({'anchor_utc':row['anchor_utc'],'reason':reason});continue
        spot=float(row['reference_spot']);sigma=float(row['past_sigma'])
        if not np.isfinite([spot,sigma]).all() or min(spot,sigma)<=0:raise ValueError('invalid observed trajectory reference or scale')
        f=np.asarray(row['features'],dtype=float)
        if f.shape!=(len(FEATURE_NAMES),) or not np.isfinite(f).all():raise ValueError('invalid verified features')
        blocks=np.array([bars[t] for t in starts]).reshape(72,12,3)
        arrays['x'].append(f);arrays['anchors'].append(at);arrays['scales'].append(sigma);arrays['spot'].append(spot)
        for name,values in (('high',blocks[:,:,0].max(1)),('low',blocks[:,:,1].min(1)),('close',blocks[:,-1,2])):
            arrays[name].append(np.log(values/spot)/sigma)
        selected.append(dict(row,complete_72h_actual_target=True))
    arrays={k:np.asarray(v,dtype=np.int64 if k=='anchors' else float) for k,v in arrays.items()}
    for k,width in (('x',len(FEATURE_NAMES)),('close',72),('high',72),('low',72)):arrays[k]=arrays[k].reshape(-1,width)
    return arrays,selected,{'accepted_rows':len(selected),'rejected_rows':rejected,'future_targets_fabricated':False,
        'full_system_ready':False,'trading_authority':False}
