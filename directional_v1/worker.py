"""Prospective, signed hourly warning for >1% 4h upside tail."""
import hashlib,json,math,os,subprocess,sys,urllib.request
from pathlib import Path
from datetime import datetime,timedelta,timezone

from alert import warn

UTC=timezone.utc
ROOT=Path(__file__).resolve().parents[1]
HERE=ROOT/'directional_v1'
EVENTS=ROOT/'directional_v1_events'
RAW=ROOT/'directional_v1_raw'
START=datetime(2026,10,2,12,tzinfo=UTC)
DEADLINE=timedelta(minutes=45)
BRANCH='btc-directional-v1'
IDENTITY='https://github.com/sergeytren1984-ux/neora-b2b-v2-clean/.github/workflows/btc-directional-v1.yml@refs/heads/main'
ISSUER='https://token.actions.githubusercontent.com'
FROZEN=('directional_v1/worker.py','directional_v1/alert.py','directional_v1/artifact.json',
        'directional_v1/protocol.json','directional_v1/selftest.py','regime_v4/model.py',
        'research_v5/data/btc_1h_2024_to_sep24_2026.json.gz')
WORKFLOW='.github/workflows/btc-directional-v1.yml'
GUARD='.github/workflows/btc-directional-v1-guard.yml'

def utcnow(): return datetime.now(UTC)
def canonical(obj): return (json.dumps(obj,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)+'\n').encode()
def digest(data): return hashlib.sha256(data).hexdigest()
def cmd(*args): return subprocess.run(args,check=True,capture_output=True,text=True,timeout=120).stdout.strip()
def bundle_time(path):
    b=json.loads(path.read_bytes()); entries=b.get('verificationMaterial',{}).get('tlogEntries',[])
    if not entries: raise ValueError('Rekor entry missing')
    for e in entries:
        proof=e.get('inclusionProof')
        if not isinstance(proof,dict) or not proof.get('checkpoint') or 'hashes' not in proof:
            raise ValueError('Rekor inclusion proof missing')
    return min(datetime.fromtimestamp(int(e['integratedTime']),UTC) for e in entries)
def verify(path,bundle):
    cmd('cosign','verify-blob',str(path),'--bundle',str(bundle),
        '--certificate-identity',IDENTITY,'--certificate-oidc-issuer',ISSUER)
    return bundle_time(bundle)
def prior_events():
    EVENTS.mkdir(exist_ok=True)
    files=sorted(p for p in EVENTS.glob('*.json') if len(p.stem)==8 and p.stem.isdigit())
    out=[]; prev=None; keys=set()
    for i,p in enumerate(files,1):
        integrated=verify(p,p.with_suffix('.sigstore.json'))
        b=p.read_bytes(); e=json.loads(b)
        if b!=canonical(e) or e.get('sequence')!=i or e.get('previous_hash')!=prev:
            raise ValueError('event hash chain broken')
        if e.get('idempotency_key') in keys: raise ValueError('duplicate event key')
        keys.add(e['idempotency_key']);prev=digest(b);out.append((e,integrated))
    return out
def remote_clean():
    cmd('git','fetch','origin',BRANCH)
    if cmd('git','rev-parse','HEAD')!=cmd('git','rev-parse','origin/'+BRANCH):
        raise RuntimeError('remote branch advanced')
def publish(obj,deadline=None,attachments=()):
    if deadline and utcnow()>=deadline-timedelta(minutes=4):
        raise TimeoutError('no new publication in deadline safety margin')
    remote_clean(); prior=prior_events();keys={e['idempotency_key'] for e,_ in prior}
    if obj['idempotency_key'] in keys: return
    n=len(prior)+1
    e={'schema':'btc-directional-v1-event-v1','sequence':n,
       'previous_hash':digest(canonical(prior[-1][0])) if prior else None,
       'workflow_commit':os.environ['GITHUB_SHA'],'published_at_utc':utcnow().isoformat(),**obj}
    p=EVENTS/f'{n:08d}.json'; b=p.with_suffix('.sigstore.json')
    p.write_bytes(canonical(e))
    cmd('cosign','sign-blob','--yes','--bundle',str(b),str(p))
    if deadline and (bundle_time(b)>=deadline or utcnow()>=deadline):
        p.unlink(missing_ok=True);b.unlink(missing_ok=True)
        raise TimeoutError('signed forecast missed deadline')
    verify(p,b)
    for x in (p,b,*attachments):cmd('git','add',str(x.relative_to(ROOT)))
    cmd('git','commit','-m',f"BTC directional v1 evidence #{n}: {e['type']}")
    cmd('git','push','origin','HEAD:'+BRANCH)
    # If publication crosses deadline the event remains signed but is late.
    if deadline and utcnow()>=deadline: raise TimeoutError('remote publication after deadline')
    if cmd('git','ls-remote','origin','refs/heads/'+BRANCH).split()[0]!=cmd('git','rev-parse','HEAD'):
        raise RuntimeError('remote publication unconfirmed')
def manifest():
    cmd('git','fetch','origin','main')
    paths={name:digest((ROOT/name).read_bytes()) for name in FROZEN}
    for name in (WORKFLOW,GUARD):
        paths[name]=digest(subprocess.run(['git','show','origin/main:'+name],check=True,capture_output=True).stdout)
    return {'paths_sha256':paths,'python_version':'.'.join(map(str,sys.version_info[:3])),
            'cosign_version':cmd('cosign','version'),'branch':BRANCH}
def candles_at(anchor):
    req=urllib.request.Request('https://data-api.binance.vision/api/v3/klines?symbol=BTCUSDT&interval=1h&limit=1000',
                               headers={'User-Agent':'btc-directional-v1'})
    with urllib.request.urlopen(req,timeout=25) as response:
        if response.status!=200:raise RuntimeError('Binance HTTP not 200')
        raw=json.loads(response.read())
    if len(raw)<889: raise ValueError('insufficient candles')
    closed=[]
    for x in raw:
        t=datetime.fromtimestamp(int(x[0])/1000,UTC)
        if int(x[6])!=int((t+timedelta(hours=1)).timestamp()*1000)-1:
            raise ValueError('candle close timestamp invalid')
        if t+timedelta(hours=1)>anchor:continue
        o,h,l,c=map(float,(x[1],x[2],x[3],x[4]));vol=float(x[5]);taker=float(x[9]);trades=int(x[8])
        if not all(map(math.isfinite,(o,h,l,c,vol,taker))) or min(o,h,l,c)<=0 or l>min(o,c) or h<max(o,c) or h<l or vol<0 or taker<0 or taker>vol or trades<0:
            raise ValueError('invalid OHLC or activity')
        closed.append({'open_time':t.isoformat(),'close_time':(t+timedelta(hours=1)).isoformat(),
                       'open':o,'high':h,'low':l,'close':c,'volume':vol,'trades':trades,'taker_buy_base':taker})
    if len(closed)<889 or datetime.fromisoformat(closed[-1]['close_time'])!=anchor:
        raise ValueError('latest closed candle != anchor or insufficient history')
    if any(datetime.fromisoformat(b['open_time'])-datetime.fromisoformat(a['open_time'])!=timedelta(hours=1) for a,b in zip(closed,closed[1:])):
        raise ValueError('candle gap or duplicate')
    return raw,closed
def main():
    t=utcnow();proto=json.loads((HERE/'protocol.json').read_bytes());ev=prior_events()
    if proto['start_utc']!=START.strftime('%Y-%m-%dT%H:%M:%SZ'):raise ValueError('start mismatch')
    if not ev:
        if t>=START:raise RuntimeError('no registration before start')
        publish({'type':'SCHEDULE_REGISTERED','idempotency_key':'directional-v1-schedule',
                 'start_utc':START.isoformat(),'deadline_minutes':45,'protocol_sha256':digest((HERE/'protocol.json').read_bytes())})
        ev=prior_events()
    if not any(e['type']=='CONFIG_FROZEN_PRESTART' for e,_ in ev):
        if t>=START:raise RuntimeError('no freeze before start')
        m=manifest();p=HERE/'frozen_manifest.json';p.write_bytes(canonical(m))
        publish({'type':'CONFIG_FROZEN_PRESTART','idempotency_key':'directional-v1-freeze',
                 'start_utc':START.isoformat(),'manifest_sha256':digest(p.read_bytes()),'manifest':m},attachments=(p,))
        return
    keys={e['idempotency_key'] for e,_ in prior_events()}
    anchor=t.replace(minute=0,second=0,microsecond=0)
    slot=anchor.strftime('%Y%m%dT%H%M%SZ')
    for e,_ in ev:
        if e['type']!='DIRECTIONAL_4H_ALERT_ISSUED':continue
        key='outcome:'+e['slot']
        if key in keys or datetime.fromisoformat(e['due_utc'])>t:continue
        try:
            outcome_raw,cs=candles_at(datetime.fromisoformat(e['due_utc']))
            actual=float(cs[-1]['close'])/float(e['reference_price'])-1>0.01
            RAW.mkdir(exist_ok=True)
            outcome_path=RAW/(e['slot']+'-4h-outcome.json')
            outcome_path.write_bytes(canonical({'slot':e['slot'],'due_utc':e['due_utc'],
                                                'retrieved_at_utc':utcnow().isoformat(),'klines':outcome_raw}))
            publish({'type':'OUTCOME_RECORDED','idempotency_key':key,'slot':e['slot'],
                     'due_utc':e['due_utc'],'actual_rise_gt_1pct':actual,'close':cs[-1]['close'],
                     'raw_path':str(outcome_path.relative_to(ROOT)),'raw_sha256':digest(outcome_path.read_bytes())},
                    attachments=(outcome_path,))
            keys.add(key)
        except (ValueError,TimeoutError,urllib.error.URLError):pass
    slot_dt=START
    while slot_dt+DEADLINE<=t:
        old=slot_dt.strftime('%Y%m%dT%H%M%SZ')
        if 'alert:'+old not in keys and 'missed:'+old not in keys:
            publish({'type':'SLOT_MISSED','idempotency_key':'missed:'+old,'slot':old,
                     'reason':'NO_TIMELY_ALERT','deadline_utc':(slot_dt+DEADLINE).isoformat()})
            keys.add('missed:'+old)
        slot_dt+=timedelta(hours=1)
    if anchor<START or t>=anchor+DEADLINE or 'alert:'+slot in keys:return
    if json.loads((HERE/'frozen_manifest.json').read_bytes())!=manifest():
        if 'abstain-config:'+slot not in keys:
            publish({'type':'ABSTAIN_CONFIG_DRIFT','idempotency_key':'abstain-config:'+slot,
                     'slot':slot,'reason':'frozen manifest mismatch; inference prohibited'},deadline=anchor+DEADLINE)
        return
    try:
        raw,closed=candles_at(anchor)
        artifact=json.loads((HERE/'artifact.json').read_bytes())
        output=warn(closed,artifact)
    except Exception as ex:
        k='abstain:'+slot
        if k not in keys:
            publish({'type':'ABSTAIN_DATA_INVALID','idempotency_key':k,'slot':slot,
                     'reason':type(ex).__name__+': '+str(ex)[:300],'retryable_before_deadline':True},deadline=anchor+DEADLINE)
        return
    RAW.mkdir(exist_ok=True)
    p=RAW/(slot+'.json');p.write_bytes(canonical({'slot':slot,'source':'Binance spot 1h klines',
                                                'retrieved_at_utc':utcnow().isoformat(),'klines':raw}))
    publish({'type':'DIRECTIONAL_4H_ALERT_ISSUED','idempotency_key':'alert:'+slot,
             'slot':slot,'anchor_utc':anchor.isoformat(),'due_utc':(anchor+timedelta(hours=4)).isoformat(),
             'reference_price':closed[-1]['close'],'output':output,'raw_path':str(p.relative_to(ROOT)),
             'raw_sha256':digest(p.read_bytes()),'artifact_sha256':digest((HERE/'artifact.json').read_bytes()),
             'trading_authority':False},deadline=anchor+DEADLINE,attachments=(p,))
if __name__=='__main__':main()
