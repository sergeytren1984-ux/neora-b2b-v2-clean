"""Independent arithmetic audit of immutable signed forward records.

One observed outcome establishes neither a predictive edge nor trade readiness.
The frozen source publishes its own scores; this module recalculates them.
"""
import datetime as dt
import hashlib
import json
import pathlib
import numpy as np
import forecast as f

SOURCE_SHA='a3c0827ae39c849f3626dcaba3c702ab5b0557d2'
IDENTITY='https://github.com/sergeytren1984-ux/neora-b2b-v2-clean/.github/workflows/btc-v7r3-signed-demand-shadow.yml@refs/heads/btc-core-distribution-forward-20261013'
ISSUER='https://token.actions.githubusercontent.com'

def verify_pair(prediction_path,outcome_path,verifier):
    pp,op=map(pathlib.Path,(prediction_path,outcome_path))
    for p in (pp,op):verifier.verify(p,IDENTITY,ISSUER,SOURCE_SHA)
    pred=json.loads(pp.read_bytes());observed=json.loads(op.read_bytes())
    if pred.get('kind')!='FORECAST' or pred.get('source_sha')!=SOURCE_SHA:raise ValueError('wrong forecast source')
    if observed['forecast_sha256']!=hashlib.sha256(pp.read_bytes()).hexdigest():raise ValueError('outcome linked to another forecast')
    if observed['anchor_utc']!=pred['anchor_utc']:raise ValueError('anchor mismatch')
    hours=observed['horizon_hours']
    if hours not in (1,4,24):raise ValueError('endpoint audit requires 1, 4 or 24 hours')
    anchor=f.stamp(pred['anchor_utc']);end=anchor+hours*3600000
    computed=f.stamp(pred['computed_at_utc'])
    if not anchor<=computed<=anchor+600000:raise ValueError('forecast computed outside registered deadline')
    bundle=json.loads(pathlib.Path(str(pp)+'.sigstore.json').read_bytes())
    log_times=[int(entry['integratedTime'])*1000 for entry in bundle['verificationMaterial']['tlogEntries']]
    if not log_times or not all(computed-1000<=t<=anchor+600000 and t<end for t in log_times):raise ValueError('forecast was not signed within its deadline before outcome')
    if f.stamp(observed['received_at_utc'])<end:raise ValueError('premature outcome')
    rows=observed['outcome_rows']
    if len(rows)!=hours*12:raise ValueError('wrong outcome row count')
    for i,row in enumerate(rows):
        if int(row[0])!=anchor+i*300000 or int(row[6])+1!=anchor+(i+1)*300000:raise ValueError('outcome grid gap')
        o,h,l,c=map(float,row[1:5])
        if not np.isfinite([o,h,l,c]).all() or not 0<l<=min(o,c)<=max(o,c)<=h:raise ValueError('invalid actual OHLC')
    spot=float(pred['reference_spot']);truth=float(rows[-1][4]);barrier={1:.007,4:.012,24:.02}[hours]
    if not np.isfinite(spot) or spot<=0:raise ValueError('invalid forecast reference price')
    r=np.log(truth/spot);label=0 if r>=np.log1p(barrier) else (1 if r<=np.log1p(-barrier) else 2)
    scores={}
    for kind,heads in pred['samples_log_returns'].items():
        values=np.asarray(heads[str(hours)],dtype=float)
        if not len(values) or not np.isfinite(values).all():raise ValueError('invalid predicted returns')
        prices=spot*np.exp(values);lo,mid,hi=np.quantile(prices,[.1,.5,.9])
        probs=np.array([(values>=np.log1p(barrier)).mean(),(values<=np.log1p(-barrier)).mean(),((values>np.log1p(-barrier))&(values<np.log1p(barrier))).mean()])
        result={'crps':f.crps(prices,truth),'mae':float(abs(mid-truth)),'coverage_80pct':bool(lo<=truth<=hi),'brier':float(np.sum((probs-np.eye(3)[label])**2))}
        for key,val in result.items():
            claimed=observed['scores'][kind][key]
            if isinstance(val,bool):
                if claimed is not val:raise ValueError('published coverage mismatch')
            elif not np.isclose(claimed,val,rtol=1e-10,atol=1e-8):raise ValueError('published score mismatch')
        scores[kind]=result
    candidate=scores['candidate']
    return {'schema':'btc-independent-forward-endpoint-audit-v1','anchor_utc':pred['anchor_utc'],'horizon_hours':hours,
        'forecast_sha256':hashlib.sha256(pp.read_bytes()).hexdigest(),'outcome_sha256':hashlib.sha256(op.read_bytes()).hexdigest(),
        'signature_identity_source_and_rekor_verified':True,'forecast_signed_before_outcome':True,
        'initial_public_release_independently_proven':False,'actual_endpoint':truth,'reference_spot':spot,
        'independently_recomputed_scores':scores,
        'crps_gain_vs_baselines':{k:s['crps']-candidate['crps'] for k,s in scores.items() if k!='candidate'},
        'single_outcome_is_not_skill_evidence':True,'prospective_skill_proven':False,'full_system_ready':False,'trading_authority':False}
