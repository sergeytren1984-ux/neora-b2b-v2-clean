"""Signed daily fixed-barrier questions and due-only observations. No predictive model."""
from __future__ import annotations
import hashlib,json,math,os,subprocess,sys,tempfile,urllib.request
from pathlib import Path
from datetime import datetime,timedelta,timezone

UTC=timezone.utc
ROOT=Path(__file__).resolve().parents[1]
HERE=ROOT/'first_passage_v1';EVENTS=ROOT/'first_passage_v1_events';RAW=ROOT/'first_passage_v1_raw'
BRANCH='btc-first-passage-v1';START=datetime(2026,10,3,14,tzinfo=UTC);DEADLINE=timedelta(minutes=45)
IDENTITY='https://github.com/sergeytren1984-ux/neora-b2b-v2-clean/.github/workflows/btc-first-passage-v1.yml@refs/heads/main'
ISSUER='https://token.actions.githubusercontent.com'
FROZEN=('first_passage_v1/worker.py','first_passage_v1/selftest.py','first_passage_v1/protocol.json')
WORKFLOW='.github/workflows/btc-first-passage-v1.yml';GUARD='.github/workflows/btc-first-passage-v1-guard.yml'

def now():return datetime.now(UTC)
def canon(v):return (json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)+'\n').encode()
def sha(v):return hashlib.sha256(v).hexdigest()
def run(*args):return subprocess.run(args,check=True,capture_output=True,text=True,timeout=120).stdout.strip()
def stamp(s):return datetime.fromisoformat(s.replace('Z','+00:00'))
def integrated(bundle):
    entries=json.loads(bundle)['verificationMaterial']['tlogEntries']
    if not entries or any(not e.get('inclusionProof',{}).get('checkpoint') or 'hashes' not in e['inclusionProof'] for e in entries):
        raise ValueError('missing Rekor inclusion proof')
    return min(datetime.fromtimestamp(int(e['integratedTime']),UTC) for e in entries)
def verify(blob,bundle):
    with tempfile.TemporaryDirectory() as td:
        a=Path(td)/'event.json';b=Path(td)/'event.sigstore.json'
        a.write_bytes(blob);b.write_bytes(bundle)
        run('cosign','verify-blob',str(a),'--bundle',str(b),
            '--certificate-identity',IDENTITY,'--certificate-oidc-issuer',ISSUER)
    return integrated(bundle)
def previous():
    EVENTS.mkdir(exist_ok=True);prev=None;keys=set();out=[]
    paths=sorted(p for p in EVENTS.glob('*.json') if len(p.stem)==8 and p.stem.isdigit())
    for n,p in enumerate(paths,1):
        blob=p.read_bytes();e=json.loads(blob)
        t=verify(blob,p.with_suffix('.sigstore.json').read_bytes())
        if blob!=canon(e) or e.get('sequence')!=n or e.get('previous_hash')!=prev or e.get('idempotency_key') in keys:
            raise ValueError('event chain broken or duplicate')
        keys.add(e['idempotency_key']);prev=sha(blob);out.append((e,t))
    return out

def publish(obj,deadline=None,attachments=()):
    if deadline and now()>=deadline-timedelta(minutes=4):raise TimeoutError('deadline safety margin')
    run('git','fetch','origin',BRANCH)
    if run('git','rev-parse','HEAD')!=run('git','rev-parse','origin/'+BRANCH):raise RuntimeError('remote advanced; retry')
    prior=previous()
    if obj['idempotency_key'] in {e['idempotency_key'] for e,_ in prior}:return
    n=len(prior)+1
    e={'schema':'btc-first-passage-event-v1','sequence':n,
       'previous_hash':sha(canon(prior[-1][0])) if prior else None,
       'workflow_commit':os.environ['GITHUB_SHA'],'published_at_utc':now().isoformat(),**obj}
    p=EVENTS/f'{n:08d}.json';bundle=p.with_suffix('.sigstore.json');p.write_bytes(canon(e))
    run('cosign','sign-blob','--yes','--bundle',str(bundle),str(p))
    if deadline and (integrated(bundle.read_bytes())>=deadline or now()>=deadline):
        p.unlink(missing_ok=True);bundle.unlink(missing_ok=True);raise TimeoutError('signed after deadline')
    verify(p.read_bytes(),bundle.read_bytes())
    for item in (p,bundle,*attachments):run('git','add',str(item.relative_to(ROOT)))
    run('git','commit','-m',f"BTC first passage #{n}: {e['type']}")
    run('git','push','origin','HEAD:'+BRANCH)
    if deadline and now()>=deadline:raise TimeoutError('remote publication late')

def manifest():
    run('git','fetch','origin','main')
    paths={p:sha((ROOT/p).read_bytes()) for p in FROZEN}
    paths.update({p:sha(subprocess.run(['git','show','origin/main:'+p],check=True,capture_output=True).stdout) for p in (WORKFLOW,GUARD)})
    return {'paths_sha256':paths,'branch':BRANCH,'python_version':'.'.join(map(str,sys.version_info[:3])),
            'cosign_version':run('cosign','version')}

def klines(start,end,count):
    url=('https://data-api.binance.vision/api/v3/klines?symbol=BTCUSDT&interval=1h&'
         f'startTime={int(start.timestamp()*1000)}&endTime={int(end.timestamp()*1000)-1}&limit=1000')
    req=urllib.request.Request(url,headers={'User-Agent':'btc-first-passage-v1'})
    with urllib.request.urlopen(req,timeout=25) as response:
        if response.status!=200:raise RuntimeError('Binance HTTP error')
        payload=response.read()
    rows=json.loads(payload)
    if len(rows)!=count:raise ValueError('missing hourly candles')
    for j,x in enumerate(rows):
        opened=int(x[0]);target=int(start.timestamp()*1000)+j*3600000
        if opened!=target or int(x[6])!=target+3599999:raise ValueError('partial, gap or duplicate hour')
        o,h,l,c,v=map(float,(x[1],x[2],x[3],x[4],x[5]))
        if not all(map(math.isfinite,(o,h,l,c,v))) or min(o,h,l,c)<=0 or l>min(o,c) or h<max(o,c) or v<0:
            raise ValueError('invalid OHLC or volume')
    return {'retrieved_at_utc':now().isoformat(),'url':url,'klines':rows}

def first_passage(rows,lower,upper):
    for x in rows:
        down=float(x[3])<=lower;up=float(x[2])>=upper
        if down and up:return 'ambiguous'
        if down:return 'lower_first'
        if up:return 'upper_first'
    return 'neither'

def main():
    t=now();protocol=json.loads((HERE/'protocol.json').read_bytes())
    if protocol['start_utc']!=START.strftime('%Y-%m-%dT%H:%M:%SZ'):raise ValueError('start mismatch')
    ev=previous()
    if not ev:
        if t>=START:raise RuntimeError('not registered before start')
        publish({'type':'SCHEDULE_REGISTERED','idempotency_key':'barrier-schedule',
                 'start_utc':START.isoformat(),'protocol_sha256':sha((HERE/'protocol.json').read_bytes())})
        ev=previous()
    if not any(e['type']=='CONFIG_FROZEN_PRESTART' for e,_ in ev):
        if t>=START:raise RuntimeError('not frozen before start')
        m=manifest();p=HERE/'frozen_manifest.json';p.write_bytes(canon(m))
        publish({'type':'CONFIG_FROZEN_PRESTART','idempotency_key':'barrier-freeze',
                 'start_utc':START.isoformat(),'manifest_sha256':sha(p.read_bytes()),'manifest':m},attachments=(p,))
        return
    keys={e['idempotency_key'] for e,_ in ev}
    if json.loads((HERE/'frozen_manifest.json').read_bytes())!=manifest():raise ValueError('frozen manifest drift')
    for e,_ in ev:
        if e['type']!='BARRIER_QUESTION_ISSUED':continue
        key='barrier-outcome:'+e['slot']+':'+e['scenario_id']
        if key in keys or t<stamp(e['due_utc']):continue
        try:
            start=stamp(e['anchor_utc']);due=stamp(e['due_utc']);h=int(e['horizon_hours'])
            raw=klines(start,due,h)
            label=first_passage(raw['klines'],float(e['lower_usdt']),float(e['upper_usdt']))
            RAW.mkdir(exist_ok=True);p=RAW/(e['slot']+'-'+e['scenario_id']+'-outcome.json')
            p.write_bytes(canon({'slot':e['slot'],'scenario_id':e['scenario_id'],'source':raw}))
            publish({'type':'BARRIER_OUTCOME_RECORDED','idempotency_key':key,
                     'slot':e['slot'],'scenario_id':e['scenario_id'],'due_utc':e['due_utc'],
                     'outcome':label,'raw_path':str(p.relative_to(ROOT)),'raw_sha256':sha(p.read_bytes()),
                     'paired_question_sha256':sha(canon(e))},attachments=(p,))
            keys.add(key)
        except (ValueError,TimeoutError,urllib.error.URLError):pass
    day=START
    while day+DEADLINE<=t:
        slot=day.strftime('%Y%m%dT%H%M%SZ')
        for s in protocol['scenarios']:
            key='barrier:'+slot+':'+s['id']
            if key not in keys and 'barrier-missed:'+slot+':'+s['id'] not in keys and 'barrier-ineligible:'+slot+':'+s['id'] not in keys:
                publish({'type':'SLOT_MISSED','idempotency_key':'barrier-missed:'+slot+':'+s['id'],
                         'slot':slot,'scenario_id':s['id'],'deadline_utc':(day+DEADLINE).isoformat(),
                         'reason':'NO_TIMELY_BARRIER_QUESTION'})
                keys.add('barrier-missed:'+slot+':'+s['id'])
        day+=timedelta(days=1)
    anchor=t.replace(hour=14,minute=0,second=0,microsecond=0)
    if anchor<START or t>=anchor+DEADLINE:return
    slot=anchor.strftime('%Y%m%dT%H%M%SZ')
    if all(any(prefix+slot+':'+s['id'] in keys for prefix in ('barrier:','barrier-ineligible:')) for s in protocol['scenarios']):return
    raw=klines(anchor-timedelta(hours=1),anchor,1)
    price=float(raw['klines'][0][4]);RAW.mkdir(exist_ok=True)
    p=RAW/(slot+'-anchor.json');p.write_bytes(canon({'slot':slot,'source':raw}))
    for s in protocol['scenarios']:
        key='barrier:'+slot+':'+s['id']
        if key in keys or 'barrier-ineligible:'+slot+':'+s['id'] in keys:continue
        if not s['lower_usdt']<price<s['upper_usdt']:
            publish({'type':'BARRIER_INELIGIBLE','idempotency_key':'barrier-ineligible:'+slot+':'+s['id'],
                     'slot':slot,'scenario_id':s['id'],'reference_price':price,
                     'reason':'reference outside precommitted barriers'},deadline=anchor+DEADLINE)
            continue
        publish({'type':'BARRIER_QUESTION_ISSUED','idempotency_key':key,
                 'slot':slot,'scenario_id':s['id'],'anchor_utc':anchor.isoformat(),
                 'due_utc':(anchor+timedelta(hours=s['horizon_hours'])).isoformat(),
                 'horizon_hours':s['horizon_hours'],'reference_price':price,
                 'lower_usdt':s['lower_usdt'],'upper_usdt':s['upper_usdt'],
                 'outcome_classes':protocol['classes'],'probability':None,'trading_authority':False,
                 'raw_path':str(p.relative_to(ROOT)),'raw_sha256':sha(p.read_bytes())},
                deadline=anchor+DEADLINE,attachments=(p,))
        keys.add(key)
if __name__=='__main__':main()
