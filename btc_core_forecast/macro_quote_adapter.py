"""Verify old signed quote receipts and replay numeric values before an as-of join.

The old workflow checks out a mutable collector branch. Its signatures do not
prove immutable collector code; that limitation survives every successful replay.
"""
import base64,datetime as dt,hashlib,json,pathlib,urllib.parse
from zoneinfo import ZoneInfo
import numpy as np
from btc_core_observer.sigstore_verify import certificate_sha

PINS=('2c8b22d75c8dd2cf5ae55770e661267f5ed8ca1a','9f843873541d30b3de3e1e0129fe9c8b0e459589',
    'baa3ba3f90c68acb7ac69418cd876b1fdd3c8f95','c2e482b65dc27c9c8bd3b812476b012d62ac7f7e','d01eed79c869c74ab0c2407eb5be92041af54ade')
IDENTITY='https://github.com/sergeytren1984-ux/neora-b2b-v2-clean/.github/workflows/btc-context-evidence.yml@refs/heads/main'
ISSUER='https://token.actions.githubusercontent.com'
SYMBOLS={'dxy':'DX-Y.NYB','nasdaq_futures':'NQ=F','us10y':'^TNX'}
MARKET_NAMES=('dxy_quoted_index','dxy_quote_age_seconds','nasdaq_futures_quote','nasdaq_quote_age_seconds','tnx_quoted_index','tnx_quote_age_seconds','tnx_previous_session_flag')

def stamp(s):
    at=dt.datetime.fromisoformat(s.replace('Z','+00:00'))
    if at.tzinfo is None:raise ValueError('timezone required')
    return at.astimezone(dt.timezone.utc)

def replay(factor,symbol):
    if factor.get('status')!='VALID':raise ValueError('quote unavailable')
    receipt=factor['receipt'];raw=base64.b64decode(receipt['raw_response_b64'],validate=True)
    if hashlib.sha256(raw).hexdigest()!=receipt['sha256']:raise ValueError('HTTP payload digest mismatch')
    for key in ('requested_url','final_url'):
        u=urllib.parse.urlparse(receipt[key])
        if u.scheme!='https' or u.hostname not in ('query1.finance.yahoo.com','query2.finance.yahoo.com'):raise ValueError('wrong quote publisher')
        if urllib.parse.unquote(u.path.rsplit('/',1)[-1])!=symbol:raise ValueError('quote symbol substitution')
    if receipt['http_status']!=200:raise ValueError('HTTP receipt failed')
    root=json.loads(raw)['chart']
    if root.get('error') is not None or len(root['result'])!=1:raise ValueError('invalid provider chart')
    result=root['result'][0];meta=result['meta']
    if meta['symbol']!=symbol:raise ValueError('provider symbol mismatch')
    times=result.get('timestamp') or [];closes=(result.get('indicators',{}).get('quote') or [{}])[0].get('close') or []
    points=[(t,v) for t,v in zip(times,closes) if v is not None]
    timestamp,value=points[-1] if points else (meta.get('regularMarketTime'),meta.get('regularMarketPrice'))
    if timestamp is None or value is None or not np.isfinite(value) or value<=0:raise ValueError('no valid quoted value')
    observed=dt.datetime.fromtimestamp(int(timestamp),dt.timezone.utc);received=stamp(receipt['retrieved_at_utc'])
    if observed>received:raise ValueError('future quoted observation')
    if not np.isclose(value,factor['value'],rtol=1e-12,atol=1e-10) or observed!=stamp(factor['source_timestamp_utc']):raise ValueError('stored quote not reproduced from HTTP body')
    return {'value':float(value),'observed':observed,'received':received,'symbol':symbol,'raw_sha256':receipt['sha256']}

def extract(path,verifier):
    path=pathlib.Path(path);sha=certificate_sha(str(path)+'.sigstore.json')
    if sha not in PINS:raise ValueError('context source not in inspected workflow profiles')
    verifier.verify(path,IDENTITY,ISSUER,sha);doc=json.loads(path.read_bytes())
    quotes={name:replay(doc['factors'][name],symbol) for name,symbol in SYMBOLS.items()}
    bundle=json.loads(pathlib.Path(str(path)+'.sigstore.json').read_bytes())
    signed=max(dt.datetime.fromtimestamp(int(t['integratedTime']),dt.timezone.utc) for t in bundle['verificationMaterial']['tlogEntries'])
    available=max(signed,*[q['received'] for q in quotes.values()])
    return {'quotes':quotes,'available_at':available,'source_sha':sha,'record_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
        'signature_and_numeric_replay_verified':True,'immutable_collector_source_proven':False,
        'calendar_primary_receipt_in_old_record_verified':False,'full_system_ready':False,'trading_authority':False}

def asof(record,at):
    at=stamp(at);reasons=[];values=[]
    if record['available_at']>at:reasons.append('MACRO_CONTEXT_NOT_YET_AVAILABLE')
    prior_session=0
    for name in SYMBOLS:
        q=record['quotes'][name];age=(at-q['observed']).total_seconds();valid=0<=age<=1800
        if name=='us10y' and not valid:
            local=at.astimezone(ZoneInfo('America/New_York'));minute=local.hour*60+local.minute
            closed=local.weekday()>=5 or minute<570 or minute>990
            if closed and 0<=age<=(72 if local.weekday()>=5 else 18)*3600:valid=True;prior_session=1
        if not valid:reasons.append('MISSING_OR_STALE:'+name)
        values.extend((q['value'],age))
    values.append(prior_session)
    return {'available':not reasons,'features':values if not reasons else None,'feature_names':list(MARKET_NAMES),
        'reasons':reasons,'record_sha256':record['record_sha256'],'source_sha':record['source_sha'],
        'available_at_utc':record['available_at'].isoformat(),'signature_and_numeric_replay_verified':True,
        'immutable_collector_source_proven':False,'TNX_quote_not_assumed_to_be_a_live_Treasury_yield':True,
        'full_system_ready':False,'trading_authority':False}
