"""Prospective signed interpretation of three frozen, independently signed heads."""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from rules import decide

UTC=timezone.utc
ROOT=Path(__file__).resolve().parents[1]
HERE=ROOT/'arbiter_v5'
EVENTS=ROOT/'arbiter_v5_events'
BRANCH='btc-arbitration-v5'
START=datetime(2026,10,5,0,tzinfo=UTC)
DEADLINE=timedelta(minutes=45)
IDENTITY='https://github.com/sergeytren1984-ux/neora-b2b-v2-clean/.github/workflows/btc-arbitration-v5.yml@refs/heads/main'
ISSUER='https://token.actions.githubusercontent.com'
SOURCE_IDENTITIES={
    'btc-directional-v1':'https://github.com/sergeytren1984-ux/neora-b2b-v2-clean/.github/workflows/btc-directional-v1.yml@refs/heads/main',
    'btc-regime-v4-hardened':'https://github.com/sergeytren1984-ux/neora-b2b-v2-clean/.github/workflows/btc-regime-v4-hardened.yml@refs/heads/main',
    'btc-directional-down-v1':'https://github.com/sergeytren1984-ux/neora-b2b-v2-clean/.github/workflows/btc-directional-down-v1.yml@refs/heads/main'}
FROZEN=('arbiter_v5/rules.py','arbiter_v5/worker.py','arbiter_v5/selftest.py','arbiter_v5/protocol.json','arbiter_v5/upstream_rules.py','arbiter_v5/sequencer.py')
GUARD='.github/workflows/btc-arbitration-v5-independent-guard.yml'
OUTCOME_WORKFLOW='.github/workflows/btc-arbitration-v5-outcome.yml'
WORKFLOW='.github/workflows/btc-arbitration-v5.yml'

def now():return datetime.now(UTC)
def canon(v):return (json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)+'\n').encode()
def sha(v):return hashlib.sha256(v).hexdigest()
def command(*args):return subprocess.run(args,check=True,capture_output=True,text=True,timeout=120).stdout.strip()
def git_bytes(ref,path):return subprocess.run(['git','show',ref+':'+path],check=True,capture_output=True,timeout=120).stdout
def parse_time(s):return datetime.fromisoformat(s.replace('Z','+00:00'))
def bundle_time(bundle):
    b=json.loads(bundle);entries=b.get('verificationMaterial',{}).get('tlogEntries',[])
    if not entries or any(not e.get('inclusionProof',{}).get('checkpoint') for e in entries):
        raise ValueError('missing Rekor inclusion proof')
    return min(datetime.fromtimestamp(int(e['integratedTime']),UTC) for e in entries)
def verify_bytes(blob,bundle,identity):
    if identity==IDENTITY and json.loads(blob).get('type')=='ARBITRATION_OUTCOME_RECORDED':
        identity=IDENTITY.replace('btc-arbitration-v5.yml','btc-arbitration-v5-outcome.yml')
    with tempfile.TemporaryDirectory() as tmp:
        p=Path(tmp)/'event.json';q=Path(tmp)/'event.sigstore.json'
        p.write_bytes(blob);q.write_bytes(bundle)
        command('cosign','verify-blob',str(p),'--bundle',str(q),
                '--certificate-identity',identity,'--certificate-oidc-issuer',ISSUER)
    return bundle_time(bundle)
def previous():
    EVENTS.mkdir(exist_ok=True)
    files=sorted(x for x in EVENTS.glob('*.json') if len(x.stem)==8 and x.stem.isdigit())
    out=[];prev=None;keys=set()
    for i,p in enumerate(files,1):
        blob=p.read_bytes();e=json.loads(blob)
        verify_bytes(blob,p.with_suffix('.sigstore.json').read_bytes(),IDENTITY)
        if blob!=canon(e) or e.get('sequence')!=i or e.get('previous_hash')!=prev:
            raise ValueError('arbiter event chain broken')
        if e.get('idempotency_key') in keys:raise ValueError('duplicate arbiter key')
        prev=sha(blob);keys.add(e['idempotency_key']);out.append(e)
    return out
def publish(obj,deadline=None,attachment=None):
    if deadline and now()>=deadline-timedelta(minutes=4):
        raise TimeoutError('deadline safety margin reached')
    command('git','fetch','origin',BRANCH)
    if command('git','rev-parse','HEAD')!=command('git','rev-parse','origin/'+BRANCH):
        raise RuntimeError('arbiter branch advanced; retry from fresh checkout')
    prior=previous()
    if obj['idempotency_key'] in {e['idempotency_key'] for e in prior}:return
    n=len(prior)+1
    event={'schema':'btc-arbiter-v4-event','sequence':n,
           'previous_hash':sha(canon(prior[-1])) if prior else None,
           'workflow_commit':os.environ['GITHUB_SHA'],'published_at_utc':now().isoformat(),**obj}
    p=EVENTS/f'{n:08d}.json';b=p.with_suffix('.sigstore.json')
    p.write_bytes(canon(event))
    command('cosign','sign-blob','--yes','--bundle',str(b),str(p))
    if deadline and (bundle_time(b.read_bytes())>=deadline or now()>=deadline):
        p.unlink(missing_ok=True);b.unlink(missing_ok=True)
        raise TimeoutError('signed after deadline')
    verify_bytes(p.read_bytes(),b.read_bytes(),IDENTITY)
    for x in (p,b,*((attachment,) if attachment else ())):
        command('git','add',str(x.relative_to(ROOT)))
    command('git','commit','-m',f"BTC arbitration v5 #{n}: {event['type']}")
    command('git','push','origin','HEAD:'+BRANCH)
    if deadline and now()>=deadline:raise TimeoutError('remote publication late')
def manifest():
    command('git','fetch','origin','main')
    paths={p:sha((ROOT/p).read_bytes()) for p in FROZEN}
    paths[WORKFLOW]=sha(git_bytes('origin/main',WORKFLOW))
    paths[GUARD]=sha(git_bytes('origin/main',GUARD))
    paths[OUTCOME_WORKFLOW]=sha(git_bytes('origin/main',OUTCOME_WORKFLOW))
    return {'paths_sha256':paths,'branch':BRANCH,'python_version':'.'.join(map(str,sys.version_info[:3])),
            'cosign_version':command('cosign','version')}
def source(branch,directory,slot,event_type):
    ref='origin/'+branch
    paths=command('git','ls-tree','-r','--name-only',ref,directory).splitlines()
    chosen=[]
    for path in paths:
        if not path.endswith('.json') or len(Path(path).stem)!=8 or not Path(path).stem.isdigit():continue
        blob=git_bytes(ref,path);event=json.loads(blob)
        if event.get('slot')==slot and event.get('type')==event_type:
            chosen.append((path,blob,event))
    if len(chosen)>1:raise ValueError('duplicate signed source forecast')
    if not chosen:return None
    path,blob,event=chosen[0]
    if blob!=canon(event):raise ValueError('noncanonical source event')
    integrated=verify_bytes(blob,git_bytes(ref,path[:-5]+'.sigstore.json'),SOURCE_IDENTITIES[branch])
    previous_hash=event.get('previous_hash');seq=event.get('sequence')
    if type(seq) is not int or seq<2:raise ValueError('source sequence missing')
    previous_blob=git_bytes(ref,f'{directory}/{seq-1:08d}.json')
    if sha(previous_blob)!=previous_hash:raise ValueError('source chain link mismatch')
    raw_path=event.get('raw_path');raw_sha=event.get('raw_sha256')
    if not raw_path or sha(git_bytes(ref,raw_path))!=raw_sha:
        raise ValueError('source raw digest mismatch')
    return {'path':path,'event':event,'event_sha256':sha(blob),
            'rekor_integrated_utc':integrated.isoformat(),'integrated':integrated,
            'branch_head':command('git','rev-parse',ref)}
def run():
    mode=os.environ.get('BTC_ARBITER_MODE','forecast')
    if mode not in ('forecast','outcome'):raise ValueError('unknown arbiter mode')
    t=now();protocol=json.loads((HERE/'protocol.json').read_bytes())
    if protocol['start_utc']!=START.strftime('%Y-%m-%dT%H:%M:%SZ'):
        raise ValueError('arbiter start mismatch')
    prior=previous()
    if not prior:
        if t>=START:raise RuntimeError('not preregistered before start')
        publish({'type':'SCHEDULE_REGISTERED','idempotency_key':'arbiter-v5-schedule',
                 'start_utc':START.isoformat(),'deadline_minutes':45,
                 'protocol_sha256':sha((HERE/'protocol.json').read_bytes())})
        prior=previous()
    if not any(e['type']=='CONFIG_FROZEN_PRESTART' for e in prior):
        if t>=START:raise RuntimeError('not frozen before start')
        frozen=manifest();p=HERE/'frozen_manifest.json';p.write_bytes(canon(frozen))
        publish({'type':'CONFIG_FROZEN_PRESTART','idempotency_key':'arbiter-v5-freeze',
                 'start_utc':START.isoformat(),'manifest_sha256':sha(p.read_bytes()),
                 'manifest':frozen},attachment=p)
        return
    keys={e['idempotency_key'] for e in prior}
    if mode=='forecast':
        cursor=START
        while cursor+DEADLINE<=t:
            slot=cursor.strftime('%Y%m%dT%H%M%SZ')
            if not any(k in keys for k in ('decision:'+slot+':4h','invalid:'+slot,'missed:'+slot)):
                publish({'type':'ARBITRATION_SLOT_MISSED','idempotency_key':'missed:'+slot,
                         'slot':slot,'deadline_utc':(cursor+DEADLINE).isoformat(),
                         'reason':'no timely verified directional source','action_status':'NO_DIRECTIONAL_ACTION'})
                keys.add('missed:'+slot)
            cursor+=timedelta(hours=1)
    frozen_ok=json.loads((HERE/'frozen_manifest.json').read_bytes())==manifest()
    if not frozen_ok:
        if mode=='outcome':raise ValueError('frozen arbiter manifest mismatch')
        anchor=t.replace(minute=0,second=0,microsecond=0)
        slot=anchor.strftime('%Y%m%dT%H%M%SZ')
        if anchor>=START and t<anchor+DEADLINE and not any(
                k in keys for k in ('decision:'+slot+':4h','invalid:'+slot)):
            publish({'type':'ABSTAIN_CONFIG_DRIFT','idempotency_key':'invalid:'+slot,
                     'slot':slot,'reason':'frozen arbiter manifest mismatch',
                     'action_status':'NO_DIRECTIONAL_ACTION'},deadline=anchor+DEADLINE)
        return
    if mode=='outcome':
        command('git','fetch','origin','btc-directional-v1','btc-directional-down-v1')
        for past in prior:
            if past['type']!='ARBITRATION_DECISION_ISSUED':continue
            outcome_key='outcome:'+past['slot']+':4h'
            due=parse_time(past['due_utc'])
            if outcome_key in keys or now()<due:continue
            signed_outcome=source('btc-directional-v1','directional_v1_events',past['slot'],'OUTCOME_RECORDED')
            if signed_outcome is None:continue
            down_source_present=past.get('sources',{}).get('downside') is not None
            down_outcome=(source('btc-directional-down-v1','directional_down_v1_events',
                                 past['slot'],'OUTCOME_RECORDED') if down_source_present else None)
            if down_source_present and down_outcome is None:continue
            if signed_outcome['integrated']<due:raise ValueError('outcome signed before due')
            if down_outcome is not None and down_outcome['integrated']<due:
                raise ValueError('downside outcome signed before due')
            observed=signed_outcome['event']
            if observed.get('idempotency_key')!='outcome:'+past['slot']:
                raise ValueError('outcome source key mismatch')
            if down_outcome is not None and (down_outcome['event'].get('idempotency_key')!=
                                             'down-outcome:'+past['slot'] or
                                             down_outcome['event'].get('due_utc')!=past['due_utc'] or
                                             abs(float(down_outcome['event']['close'])-float(observed['close']))>0.01):
                raise ValueError('downside outcome pairing mismatch')
            publish({'type':'ARBITRATION_OUTCOME_RECORDED','idempotency_key':outcome_key,
                     'slot':past['slot'],'due_utc':past['due_utc'],
                     'decision_event_sha256':sha(canon(past)),
                     'source_event_sha256':signed_outcome['event_sha256'],
                     'actual_rise_gt_1pct':observed['actual_rise_gt_1pct'],
                     'actual_fall_lt_minus_1pct':down_outcome['event']['actual_fall_lt_minus_1pct'] if down_outcome else None,
                     'downside_outcome_status':'VERIFIED' if down_outcome else 'NO_DOWNSIDE_SOURCE_AT_ISSUANCE',
                     'downside_source_outcome_sha256':down_outcome['event_sha256'] if down_outcome else None,
                     'close':observed['close'],
                     'warning_issued':past['directional_up_tail_alert'],
                     'downside_warning_issued':past['directional_down_tail_alert']})
            keys.add(outcome_key)
        return
    anchor=t.replace(minute=0,second=0,microsecond=0)
    slot=anchor.strftime('%Y%m%dT%H%M%SZ')
    if anchor<START or t>=anchor+DEADLINE or any(k in keys for k in ('decision:'+slot+':4h','invalid:'+slot)):
        return
    command('git','fetch','origin','btc-directional-v1','btc-regime-v4-hardened','btc-directional-down-v1')
    try:
        d=source('btc-directional-v1','directional_v1_events',slot,'DIRECTIONAL_4H_ALERT_ISSUED')
        v=source('btc-regime-v4-hardened','regime_v4_events',slot,'REGIME_FORECAST_ISSUED')
        dn=source('btc-directional-down-v1','directional_down_v1_events',slot,'DIRECTIONAL_4H_DOWNSIDE_ALERT_ISSUED')
        if d is None:return  # signed directional source is indispensable
        if (v is None or dn is None) and t<anchor+timedelta(minutes=35):return
        if any(x['integrated']<anchor or x['integrated']>=anchor+DEADLINE for x in (d,v,dn) if x is not None):
            raise ValueError('source Rekor timestamp outside prospective slot')
        for proof in v['event'].get('context_proofs',{}).values() if v is not None else ():
            if parse_time(proof['rekor_integrated_utc'])>anchor:
                raise ValueError('regime context signed after anchor')
        decision=decide(d['event'],v['event'] if v is not None else None,
                        dn['event'] if dn is not None else None,anchor=anchor)
    except (ValueError,KeyError,TypeError) as error:
        publish({'type':'ARBITRATION_SOURCE_INVALID','idempotency_key':'invalid:'+slot,
                 'slot':slot,'reason':type(error).__name__+': '+str(error)[:300],
                 'action_status':'NO_DIRECTIONAL_ACTION'},deadline=anchor+DEADLINE)
        return
    receipts={name:({k:value[k] for k in ('path','event_sha256','rekor_integrated_utc','branch_head')}
                    if value is not None else None)
              for name,value in (('directional',d),('regime',v),('downside',dn))}
    publish({'type':'ARBITRATION_DECISION_ISSUED','idempotency_key':'decision:'+slot+':4h',
             **decision,'sources':receipts},deadline=anchor+DEADLINE)

if __name__=='__main__':run()
