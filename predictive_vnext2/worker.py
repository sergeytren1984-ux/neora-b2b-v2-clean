"""Signed prospective shadow worker for predictive vNext2 candidates.

Forecast and outcome actions are physically separated by workflow. No event grants
trading authority. Historical calibration is explicitly not prospective validation.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import joblib
import numpy as np
import sklearn

from predictive_vnext2.live_features import (
    HOURLY_NAMES, EARLY15M_NAMES, hourly_feature, early15m_feature,
)
from predictive_vnext2.predict import load_artifact, predict_competing_risks, control_prediction

UTC=timezone.utc
ROOT=Path(__file__).resolve().parents[1]
HERE=ROOT/'predictive_vnext2'
START=datetime(2026,10,5,0,0,tzinfo=UTC)
ISSUER='https://token.actions.githubusercontent.com'

CONFIG={
    'hourly': {
        'branch':'btc-predictive-vnext2-hourly',
        'protocol':'predictive_vnext2/protocol_hourly.json',
        'artifact':'predictive_vnext2/hourly_rv72_competing_risks.joblib',
        'events':'predictive_vnext2_hourly_events',
        'raw':'predictive_vnext2_hourly_raw',
        'cadence':timedelta(hours=1),
        'deadline':timedelta(minutes=45),
        'interval':'1h','duration_ms':3600000,'min_history':170,
        'forecast_workflow':'.github/workflows/btc-predictive-vnext2-hourly.yml',
        'outcome_workflow':'.github/workflows/btc-predictive-vnext2-hourly-outcome.yml',
    },
    'early15m': {
        'branch':'btc-predictive-vnext2-early15m',
        'protocol':'predictive_vnext2/protocol_early15m.json',
        'artifact':'predictive_vnext2/early15m_pm1_4h_competing_risks.joblib',
        'events':'predictive_vnext2_early15m_events',
        'raw':'predictive_vnext2_early15m_raw',
        'cadence':timedelta(minutes=15),
        'deadline':timedelta(minutes=14),
        'interval':'15m','duration_ms':900000,'min_history':385,
        'forecast_workflow':'.github/workflows/btc-predictive-vnext2-early15m.yml',
        'outcome_workflow':'.github/workflows/btc-predictive-vnext2-early15m-outcome.yml',
    }
}


def utcnow(): return datetime.now(UTC)
def canonical(obj): return (json.dumps(obj,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)+'\n').encode()
def digest(data): return hashlib.sha256(data).hexdigest()
def cmd(*args): return subprocess.run(args,check=True,capture_output=True,text=True,timeout=180).stdout.strip()

def identity(path):
    return f'https://github.com/sergeytren1984-ux/neora-b2b-v2-clean/{path}@refs/heads/main'

def bundle_time(path):
    b=json.loads(Path(path).read_bytes()); entries=b.get('verificationMaterial',{}).get('tlogEntries',[])
    if not entries: raise ValueError('Rekor entry missing')
    for e in entries:
        proof=e.get('inclusionProof')
        if not isinstance(proof,dict) or not proof.get('checkpoint') or 'hashes' not in proof:
            raise ValueError('Rekor inclusion proof missing')
    return min(datetime.fromtimestamp(int(e['integratedTime']),UTC) for e in entries)

def signer_identity(cfg,event_type):
    return identity(cfg['outcome_workflow'] if event_type=='OUTCOME_RECORDED' else cfg['forecast_workflow'])

def verify(path,bundle,cfg,event_type):
    cmd('cosign','verify-blob',str(path),'--bundle',str(bundle),
        '--certificate-identity',signer_identity(cfg,event_type),'--certificate-oidc-issuer',ISSUER)
    return bundle_time(bundle)

def prior_events(cfg):
    events=ROOT/cfg['events'];events.mkdir(exist_ok=True)
    files=sorted(p for p in events.glob('*.json') if len(p.stem)==8 and p.stem.isdigit())
    out=[];prev=None;keys=set()
    for i,p in enumerate(files,1):
        raw=p.read_bytes();e=json.loads(raw)
        integrated=verify(p,p.with_suffix('.sigstore.json'),cfg,e.get('type'))
        if raw!=canonical(e) or e.get('sequence')!=i or e.get('previous_hash')!=prev:
            raise ValueError('event hash chain broken')
        if e.get('idempotency_key') in keys: raise ValueError('duplicate event key')
        keys.add(e['idempotency_key']);prev=digest(raw);out.append((e,integrated))
    return out

def remote_clean(cfg):
    cmd('git','fetch','origin',cfg['branch'])
    if cmd('git','rev-parse','HEAD')!=cmd('git','rev-parse','origin/'+cfg['branch']):
        raise RuntimeError('remote evidence branch advanced')

def publish(cfg,obj,deadline=None,attachments=()):
    if deadline and utcnow()>=deadline-timedelta(minutes=2):
        raise TimeoutError('deadline safety margin reached')
    remote_clean(cfg);prior=prior_events(cfg);keys={e['idempotency_key'] for e,_ in prior}
    if obj['idempotency_key'] in keys:return
    n=len(prior)+1
    event={'schema':'btc-predictive-vnext2-event-v1','sequence':n,
           'previous_hash':digest(canonical(prior[-1][0])) if prior else None,
           'workflow_commit':os.environ['GITHUB_SHA'],'published_at_utc':utcnow().isoformat(),**obj}
    events=ROOT/cfg['events'];p=events/f'{n:08d}.json';b=p.with_suffix('.sigstore.json')
    p.write_bytes(canonical(event))
    cmd('cosign','sign-blob','--yes','--bundle',str(b),str(p))
    if deadline and (bundle_time(b)>=deadline or utcnow()>=deadline):
        p.unlink(missing_ok=True);b.unlink(missing_ok=True);raise TimeoutError('signed forecast missed deadline')
    verify(p,b,cfg,event['type'])
    for x in (p,b,*attachments):cmd('git','add',str(Path(x).relative_to(ROOT)))
    cmd('git','commit','-m',f"BTC predictive vNext2 {cfg['interval']} evidence #{n}: {event['type']}")
    cmd('git','push','origin','HEAD:'+cfg['branch'])
    if cmd('git','ls-remote','origin','refs/heads/'+cfg['branch']).split()[0]!=cmd('git','rev-parse','HEAD'):
        raise RuntimeError('remote publication unconfirmed')

def manifest(cfg):
    cmd('git','fetch','origin','main')
    frozen=[
        'predictive_vnext2/worker.py','predictive_vnext2/live_features.py','predictive_vnext2/predict.py',
        'predictive_vnext2/selftest.py','research_vnext2/core.py','predictive_vnext2/freeze_metadata.json',
        'research_vnext2/hourly_result.json','research_vnext2/early15m_result.json',
        cfg['protocol'],cfg['artifact']
    ]
    paths={p:digest((ROOT/p).read_bytes()) for p in frozen}
    for p in (cfg['forecast_workflow'],cfg['outcome_workflow']):
        paths[p]=digest(subprocess.run(['git','show','origin/main:'+p],check=True,capture_output=True).stdout)
    return {'schema':'btc-predictive-vnext2-frozen-manifest-v1','paths_sha256':paths,
            'python_version':'.'.join(map(str,sys.version_info[:3])),
            'numpy_version':np.__version__,'sklearn_version':sklearn.__version__,
            'joblib_version':joblib.__version__,'cosign_version':cmd('cosign','version'),
            'branch':cfg['branch']}

def initialize(cfg,head):
    now=utcnow();proto=json.loads((ROOT/cfg['protocol']).read_bytes());events=prior_events(cfg)
    if proto['start_utc']!=START.strftime('%Y-%m-%dT%H:%M:%SZ'):raise ValueError('protocol start mismatch')
    if not events:
        if now>=START:raise RuntimeError('no schedule registration before start')
        publish(cfg,{'type':'SCHEDULE_REGISTERED','idempotency_key':f'{head}:schedule',
                     'start_utc':START.isoformat(),'deadline_minutes':int(cfg['deadline'].total_seconds()/60),
                     'protocol_sha256':digest((ROOT/cfg['protocol']).read_bytes()),'trading_authority':False})
        events=prior_events(cfg)
    if not any(e['type']=='CONFIG_FROZEN_PRESTART' for e,_ in events):
        if now>=START:raise RuntimeError('no config freeze before start')
        m=manifest(cfg);p=HERE/f'frozen_manifest_{head}.json';p.write_bytes(canonical(m))
        publish(cfg,{'type':'CONFIG_FROZEN_PRESTART','idempotency_key':f'{head}:freeze',
                     'start_utc':START.isoformat(),'manifest_sha256':digest(p.read_bytes()),'manifest':m,
                     'trading_authority':False},attachments=(p,))
        return False
    return True

def slot_floor(now,cadence):
    if cadence==timedelta(hours=1):return now.replace(minute=0,second=0,microsecond=0)
    minute=(now.minute//15)*15
    return now.replace(minute=minute,second=0,microsecond=0)

def slot_text(anchor):return anchor.strftime('%Y%m%dT%H%M%SZ')

def fetch_recent(anchor,cfg):
    params=urllib.parse.urlencode({'symbol':'BTCUSDT','interval':cfg['interval'],'limit':1000})
    url='https://data-api.binance.vision/api/v3/klines?'+params
    req=urllib.request.Request(url,headers={'User-Agent':'btc-predictive-vnext2'})
    with urllib.request.urlopen(req,timeout=30) as response:
        if response.status!=200:raise RuntimeError('Binance HTTP not 200')
        raw=json.loads(response.read())
    closed=[]
    for x in raw:
        open_ms=int(x[0]);close_ms=int(x[6])
        if close_ms!=open_ms+cfg['duration_ms']-1:raise ValueError('invalid candle close timestamp')
        close_time=datetime.fromtimestamp((close_ms+1)/1000,UTC)
        if close_time>anchor:continue
        o,h,l,c=map(float,(x[1],x[2],x[3],x[4]));vol=float(x[5]);taker=float(x[9]);trades=int(x[8])
        if not all(map(math.isfinite,(o,h,l,c,vol,taker))) or min(o,h,l,c)<=0 or l>min(o,c) or h<max(o,c) or h<l or vol<0 or taker<0 or taker>vol or trades<0:
            raise ValueError('invalid OHLC/activity')
        closed.append(x)
    if len(closed)<cfg['min_history']:
        raise ValueError('insufficient closed candles')
    if datetime.fromtimestamp((int(closed[-1][6])+1)/1000,UTC)!=anchor:
        raise ValueError('latest closed candle != anchor')
    if any(int(b[0])-int(a[0])!=cfg['duration_ms'] for a,b in zip(closed,closed[1:])):
        raise ValueError('candle gap or duplicate')
    return raw,closed

def arrays(closed):
    return tuple(np.asarray([float(x[j]) for x in closed]) for j in (2,3,4,5,8,9))

def forecast(cfg,head):
    now=utcnow();anchor=slot_floor(now,cfg['cadence']);deadline=anchor+cfg['deadline']
    if anchor<START or now>=deadline:return
    ev=prior_events(cfg);keys={e['idempotency_key'] for e,_ in ev};slot=slot_text(anchor)
    if 'forecast:'+slot in keys:return
    frozen=HERE/f'frozen_manifest_{head}.json'
    if not frozen.exists() or json.loads(frozen.read_bytes())!=manifest(cfg):
        k='abstain-config:'+slot
        if k not in keys:publish(cfg,{'type':'ABSTAIN_CONFIG_DRIFT','idempotency_key':k,'slot':slot,
                                      'reason':'frozen manifest mismatch; inference prohibited'},deadline=deadline)
        return
    proto=json.loads((ROOT/cfg['protocol']).read_bytes())
    try:
        raw,closed=fetch_recent(anchor,cfg);hi,lo,c,v,trades,taker=arrays(closed)
        art=load_artifact(ROOT/cfg['artifact'],proto['artifact_sha256'])
        if head=='hourly':
            x,meta=hourly_feature(hi,lo,c,v,trades,taker)
            if art['feature_names']!=HOURLY_NAMES:raise ValueError('hourly feature schema mismatch')
            distance=meta['reference_price']*meta['rv24']*math.sqrt(72.0)
            lower=meta['reference_price']-distance;upper=meta['reference_price']+distance
            due=anchor+timedelta(hours=72);vol_value=meta['rv24']
        else:
            x,meta=early15m_feature(hi,lo,c,v,trades,taker)
            if art['feature_names']!=EARLY15M_NAMES:raise ValueError('15m feature schema mismatch')
            lower=meta['reference_price']*.99;upper=meta['reference_price']*1.01
            due=anchor+timedelta(hours=4);vol_value=meta['rv4h']
        candidate=predict_competing_risks(art,x);control=control_prediction(art,vol_value)
    except Exception as ex:
        k='abstain-data:'+slot
        if k not in keys:publish(cfg,{'type':'ABSTAIN_DATA_INVALID','idempotency_key':k,'slot':slot,
                                      'reason':type(ex).__name__+': '+str(ex)[:300],
                                      'retryable_before_deadline':True},deadline=deadline)
        return
    rawdir=ROOT/cfg['raw'];rawdir.mkdir(exist_ok=True)
    p=rawdir/(slot+'.json');p.write_bytes(canonical({'slot':slot,'anchor_utc':anchor.isoformat(),
        'retrieved_at_utc':utcnow().isoformat(),'source':'Binance BTCUSDT closed '+cfg['interval']+' klines','klines':raw}))
    publish(cfg,{'type':'FORECAST_ISSUED','idempotency_key':'forecast:'+slot,'slot':slot,
        'head':head,'anchor_utc':anchor.isoformat(),'due_utc':due.isoformat(),
        'reference_price':meta['reference_price'],'lower_price':float(lower),'upper_price':float(upper),
        'candidate_class_distribution':candidate,'control':control,
        'probability_status':'HISTORICALLY_CALIBRATED_PROSPECTIVE_UNVALIDATED',
        'artifact_sha256':proto['artifact_sha256'],'raw_path':str(p.relative_to(ROOT)),
        'raw_sha256':digest(p.read_bytes()),'trading_authority':False},deadline=deadline,attachments=(p,))

def mark_missed(cfg):
    now=utcnow();events=prior_events(cfg);keys={e['idempotency_key'] for e,_ in events}
    slot=START
    while slot+cfg['deadline']<=now:
        s=slot_text(slot)
        if 'forecast:'+s not in keys and 'missed:'+s not in keys and 'abstain-config:'+s not in keys:
            publish(cfg,{'type':'SLOT_MISSED','idempotency_key':'missed:'+s,'slot':s,
                         'reason':'NO_TIMELY_FORECAST','deadline_utc':(slot+cfg['deadline']).isoformat(),
                         'trading_authority':False})
            keys.add('missed:'+s)
        slot+=cfg['cadence']

def fetch_outcome_rows(anchor,due,cfg):
    start_ms=int(anchor.timestamp()*1000);end_ms=int(due.timestamp()*1000)-1
    params=urllib.parse.urlencode({'symbol':'BTCUSDT','interval':cfg['interval'],'startTime':start_ms,
                                   'endTime':end_ms,'limit':1000})
    url='https://data-api.binance.vision/api/v3/klines?'+params
    req=urllib.request.Request(url,headers={'User-Agent':'btc-predictive-vnext2-outcome'})
    with urllib.request.urlopen(req,timeout=30) as response:
        if response.status!=200:raise RuntimeError('Binance outcome HTTP not 200')
        rows=json.loads(response.read())
    expected=int((due-anchor).total_seconds()*1000/cfg['duration_ms'])
    if len(rows)!=expected:raise ValueError(f'outcome candle count {len(rows)} != {expected}')
    if int(rows[0][0])!=start_ms or int(rows[-1][6])+1!=int(due.timestamp()*1000):
        raise ValueError('outcome boundaries mismatch')
    if any(int(b[0])-int(a[0])!=cfg['duration_ms'] for a,b in zip(rows,rows[1:])):
        raise ValueError('outcome candle gap')
    return rows

def classify(rows,lower,upper):
    for x in rows:
        dn=float(x[3])<=lower;up=float(x[2])>=upper
        if dn and up:return 'AMBIGUOUS_SAME_BAR',datetime.fromtimestamp((int(x[6])+1)/1000,UTC).isoformat()
        if dn:return 'LOWER_FIRST',datetime.fromtimestamp((int(x[6])+1)/1000,UTC).isoformat()
        if up:return 'UPPER_FIRST',datetime.fromtimestamp((int(x[6])+1)/1000,UTC).isoformat()
    return 'NEITHER',None

def outcomes(cfg,head):
    now=utcnow();events=prior_events(cfg);keys={e['idempotency_key'] for e,_ in events}
    for e,_ in events:
        if e.get('type')!='FORECAST_ISSUED':continue
        key='outcome:'+e['slot']
        if key in keys:continue
        due=datetime.fromisoformat(e['due_utc'])
        if due>now:continue
        try:
            rows=fetch_outcome_rows(datetime.fromisoformat(e['anchor_utc']),due,cfg)
            cls,touch=classify(rows,float(e['lower_price']),float(e['upper_price']))
        except Exception:
            continue
        rawdir=ROOT/cfg['raw'];rawdir.mkdir(exist_ok=True)
        p=rawdir/(e['slot']+'-outcome.json');p.write_bytes(canonical({'slot':e['slot'],'due_utc':e['due_utc'],
            'retrieved_at_utc':utcnow().isoformat(),'klines':rows}))
        publish(cfg,{'type':'OUTCOME_RECORDED','idempotency_key':key,'slot':e['slot'],'head':head,
            'anchor_utc':e['anchor_utc'],'due_utc':e['due_utc'],'outcome_class':cls,
            'first_touch_time_utc':touch,'lower_price':e['lower_price'],'upper_price':e['upper_price'],
            'raw_path':str(p.relative_to(ROOT)),'raw_sha256':digest(p.read_bytes()),
            'trading_authority':False},attachments=(p,))
        keys.add(key)

def main():
    head=os.environ.get('BTC_VNEXT2_HEAD');action=os.environ.get('BTC_VNEXT2_ACTION')
    if head not in CONFIG or action not in ('forecast','outcome'):raise ValueError('invalid head/action')
    cfg=CONFIG[head]
    if action=='forecast':
        if not initialize(cfg,head):return
        if utcnow()<START:return
        mark_missed(cfg);forecast(cfg,head)
    else:
        if utcnow()<START:return
        if not any(e['type']=='CONFIG_FROZEN_PRESTART' for e,_ in prior_events(cfg)):
            raise RuntimeError('prospective config not frozen')
        outcomes(cfg,head)

if __name__=='__main__':main()
