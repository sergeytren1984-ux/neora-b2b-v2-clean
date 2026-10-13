"""Only AFTER target time: settle genuinely public research 1/4/24h BTC p.

No backdating, future inputs are LABELS only, the earlier public GitHub
commit timestamp is provided externally and must be verified by reviewer.
R5 snapshot signature is NOT cryptographically authenticated by this code.
Scores cannot grant trade admission, no OTC operator ASK or actual fill.
"""
from __future__ import annotations
import argparse,datetime as dt,json,hashlib,pathlib,math
from btc_skill_rebuild.research_endpoint_24h_v7r6 import brier
from btc_skill_rebuild.research_unified_endpoint_v7r6 import endpoint_class,HORIZONS
UTC=dt.timezone.utc

def when(raw):
    v=dt.datetime.fromisoformat(raw)
    if v.tzinfo is None or v.utcoffset() is None:
        raise ValueError('timezone-aware UTC evidence required')
    return v.astimezone(UTC)

def resolved_endpoint(prediction,freeze,target_snapshot,public_commit_time_utc,now_utc=None):
    slot=when(prediction['clock_anchor_utc'])
    public=when(public_commit_time_utc)
    now=when(now_utc) if now_utc else dt.datetime.now(UTC)
    if not slot<=public<=slot+dt.timedelta(minutes=13):
        raise ValueError('public research prediction missed frozen 13-minute delivery deadline')
    if not prediction.get('trading_authority') is False:
        raise ValueError('no real trading authority can be retroactively assigned')
    if not prediction.get('evidence_signature_not_independently_verified'):
        raise ValueError('research provenance must not claim cryptographic verification')
    # Research-only immutable endpoint checks; no horizon relabelling after publication.
    if set(prediction.get('three_way',{}))!=set(HORIZONS) or set(freeze.get('heads',{}))!=set(HORIZONS):
        raise ValueError('missing or substituted frozen horizon')
    reference=None
    for h,(duration,threshold) in HORIZONS.items():
        head=prediction['three_way'][h]
        locked=freeze['heads'][h]
        if int(locked['duration_5m_steps'])!=duration or float(locked['threshold'])!=threshold:
            raise ValueError('frozen target duration or threshold drift')
        if when(head['horizon_target_utc'])!=slot+dt.timedelta(minutes=duration*5):
            raise ValueError('post-event target maturity shift')
        if head.get('source_anchor_utc')!=prediction['clock_anchor_utc']:
            raise ValueError('head anchor changed after public slot')
        if float(head['endpoint_threshold_fraction'])!=threshold:
            raise ValueError('post-event threshold change')
        p=[float(head[k]) for k in ('up','down','range')]
        if any(not math.isfinite(v) or v<0 or v>1 for v in p) or abs(sum(p)-1)>1e-9:
            raise ValueError('invalid original probabilities')
        price=float(head['reference_spot_usdt'])
        if not math.isfinite(price) or price<=0 or reference is not None and price!=reference:
            raise ValueError('original reference spot changed between heads')
        reference=price
    obs=target_snapshot
    retrieved=when(obs['retrieved_at_utc'])
    anchor=when(obs['anchor_utc'])
    if retrieved>now or anchor>retrieved or anchor>now:
        raise ValueError('future or impossible snapshot receipt relative to scoring time')
    if obs.get('no_backfill') is not True:
        raise ValueError('R5 future snapshot cannot be backfilled')
    bars=obs['five_min_rows']
    close_by_end={}
    for row in bars:
        start=int(row[0]);end=int(row[6])+1
        if end-start!=300000:raise ValueError('unclosed 5m endpoint bar')
        k=dt.datetime.fromtimestamp(end/1000,UTC)
        if k in close_by_end:raise ValueError('duplicate close time in signed input')
        if k>anchor or end/1000>retrieved.timestamp():
            raise ValueError('future outcome unavailable before anchor or receipt')
        open_,high,low,close=map(float,[row[1],row[2],row[3],row[4]])
        if not all(math.isfinite(x) for x in (open_,high,low,close)) or not (
            0<low<=min(open_,close)<=max(open_,close)<=high):
            raise ValueError('invalid subsequent signed price')
        close_by_end[k]=close
    result={}
    for h,head in prediction['three_way'].items():
        target=when(head['horizon_target_utc'])
        if target>anchor:
            result[h]={'due':False,'resolved':False,'reason':'target not in as-of future outcome snapshot'}
            continue
        if target>now:
            raise ValueError('must not resolve an unclosed future target')
        if target not in close_by_end:
            result[h]={'due':True,'resolved':False,'reason':'missing exact fixed target 5m candle'}
            continue
        p=[head['up'],head['down'],head['range']]
        if len(p)!=3 or any(not math.isfinite(x) or x<0 or x>1 for x in p) or abs(sum(p)-1)>1e-9:
            raise ValueError('invalid prior public three-way probabilities')
        if abs(head['reference_spot_usdt']-prediction['three_way']['1h']['reference_spot_usdt'])>1e-9:
            raise ValueError('endpoint heads must share original exact reference price')
        y=endpoint_class(head['reference_spot_usdt'],close_by_end[target],head['endpoint_threshold_fraction'])
        frozen=freeze['heads'][h]
        prior=frozen['model_parameters'][3]
        result[h]={'due':True,'resolved':True,'target_utc':target.isoformat(),
          'actual_target_close_usdt':close_by_end[target],
          'reference_spot_usdt':head['reference_spot_usdt'],
          'actual_outcome':['UP','DOWN','RANGE'][y],
          'forecast_probabilities':{'UP':p[0],'DOWN':p[1],'RANGE':p[2]},
          'strict_3way_Brier_model':brier(p,y),
          'strict_3way_Brier_frozen_train_prior':brier(prior,y),
          'Brier_gain_vs_frozen_train_prior':brier(prior,y)-brier(p,y),
          'shrink_previous_validation_only':frozen['validation_selected_shrink']}
    due_count=sum(bool(v.get('due')) for v in result.values())
    resolved_count=sum(bool(v.get('resolved')) for v in result.values())
    missing_count=sum(bool(v.get('due')) and not bool(v.get('resolved')) for v in result.values())
    return {'schema':'btc-v7r6-research-prospective-fixed-endpoint-own-slot-v1',
        'public_model_commit_time_utc_claimed_external':public.isoformat(),
        'public_model_commit_time_NOT_crypto_checked_inside_this_module':True,
        'earliest_R5_signed_spot_input_ref':prediction['input_R5_spot_source_path'],
        'R5_signed_spot_input_Git_blob':prediction['input_R5_spot_source_blob_GitHub_sha1'],
        'future_R5_spot_snapshot_anchor_utc':obs['anchor_utc'],
        'future_R5_spot_snapshot_receipt_utc':obs['retrieved_at_utc'],
        'has_real_OTC_operator_quotes':False,
        'fixed_horizon_due_count':due_count,
        'fixed_horizon_resolved_count':resolved_count,
        'fixed_horizon_due_missing_count':missing_count,
        'calendar_days_with_any_resolved_endpoint':int(resolved_count>0),
        'independent_prospective_days_count':0,
        'independent_days_require_global_precommitted_nonoverlapping_grid':True,
        'prospective_market_skill_proven':False,'trading_authority':False,
        'three_way_horizons':result}

def run(forecast,weights,future,public_utc,out):
    pred=json.load(open(forecast));frozen=json.load(open(weights));raw=json.load(open(future))
    if hashlib.sha256(pathlib.Path(weights).read_bytes()).hexdigest()!=pred['training_weights_sha256']:
        raise ValueError('weights changed after public forecast')
    payload=resolved_endpoint(pred,frozen,raw,public_utc)
    pathlib.Path(out).write_text(json.dumps(payload,sort_keys=True,indent=2,allow_nan=False)+'\n')
    return payload

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--prediction',required=True)
    p.add_argument('--weights',required=True);p.add_argument('--future',required=True)
    p.add_argument('--public-time',required=True);p.add_argument('--out',required=True)
    args=p.parse_args();run(args.prediction,args.weights,args.future,args.public_time,args.out)