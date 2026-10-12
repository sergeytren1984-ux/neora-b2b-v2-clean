"""Prospective signed operational observer of frozen v7R5 vs frozen v7R6.

Uses ONLY independently verified v7R5 publicly released snapshots, never
future outcomes; +13 minute original publication deadline is enforced at push.
Failure, missing source, or scheduling jitter NEVER create a backfilled alert.
Not an OTC quote or a trade-authorized predictor.
"""
from __future__ import annotations
import datetime as dt,hashlib,json,math,os,pathlib,subprocess,tempfile,time,concurrent.futures
from btc_demand_v7.demand_change_v2 import advance,state_zero,source_hash,BASELINE_COUNT
from btc_demand_v7.source_integrity_v5 import rederive
from btc_demand_v7.live_snapshot import strict_closed,spot_state
from btc_demand_v7.release_guard import certificate_source_sha
from btc_demand_v7.prospective_core import when

REPO="sergeytren1984-ux/neora-b2b-v2-clean"
SRC_BRANCH="btc-v7r5-corrected-signed-evidence-20261013"
OUT_BRANCH="btc-v7r6-pinned-signed-evidence-20261013"
R5_SHA="d6acb83d45ea484d2f2c88b725faedf3de97775d"
R6_SHA="559faaa4895f8874bc7103b4f1d92f350a8d6403"
ISSUER="https://token.actions.githubusercontent.com"
R5_ID=f"https://github.com/{REPO}/.github/workflows/btc-v7r3-signed-demand-shadow.yml@refs/heads/btc-v7r5-live-cadence-reliability-20261012"
R6_ID=f"https://github.com/{REPO}/.github/workflows/btc-v7r6-pinned-live.yml@refs/heads/btc-v7r6-pinned-observer-20261012"
START=dt.datetime(2026,10,13,tzinfo=dt.timezone.utc)
END=dt.datetime(2026,10,20,tzinfo=dt.timezone.utc)
RECEIPT_DEADLINE_MINUTES=13
UTC=dt.timezone.utc

def now():return dt.datetime.now(UTC)
def call(*args,cwd=None):
    p=subprocess.run(args,cwd=cwd,capture_output=True,text=True,timeout=120)
    if p.returncode:raise RuntimeError("command failed: "+' '.join(map(str,args[:2]))+": "+p.stderr[-450:])
    return p.stdout.strip()

def canonical(x):return (json.dumps(x,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode()
def sha(x):return hashlib.sha256(canonical(x)).hexdigest()
def slug(x):return when(x).strftime('%Y%m%dT%H%MZ')
def signed(path,identity,source_sha):
    path=pathlib.Path(path)
    call('cosign','verify-blob',str(path),'--bundle',str(path)+'.sigstore.json',
         '--certificate-identity',identity,'--certificate-oidc-issuer',ISSUER)
    if certificate_source_sha(str(path)+'.sigstore.json')!=source_sha:
        raise ValueError('signed source SHA does not equal fixed frozen source')
    return json.loads(path.read_text())
def write(root,name,obj):
    p=pathlib.Path(root)/name
    if p.exists():raise RuntimeError('immutable evidence collision')
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_bytes(canonical(obj))
    call('cosign','sign-blob','--yes','--bundle',str(p)+'.sigstore.json',str(p))
    return p

def clone(out,branch,create=False):
    call('gh','auth','setup-git')
    url='https://github.com/'+REPO+'.git'
    if create:
        out.mkdir(parents=True)
        call('git','init','--quiet',cwd=out)
        call('git','remote','add','origin',url,cwd=out)
        call('git','checkout','--quiet','-b',branch,cwd=out)
    else:
        call('git','clone','--quiet','--depth','1','--branch',branch,url,str(out))
    call('git','config','user.name','btc-v7r6-prospective-collector',cwd=out)
    call('git','config','user.email','btc-v7r6-prospective-collector@users.noreply.github.com',cwd=out)

def publish(out,commit_message):
    call('git','add','btc_v7r6_evidence',cwd=out)
    call('git','commit','--quiet','-m',commit_message,cwd=out)
    for i in range(4):
        try:
            if i:call('git','pull','--rebase','origin',OUT_BRANCH,cwd=out)
            call('git','push','--quiet','origin','HEAD:refs/heads/'+OUT_BRANCH,cwd=out)
            return
        except RuntimeError:
            if i==3:raise
            time.sleep(2**i)

def verify_runner():
    runner=os.environ.get('RUNNER_SOURCE_SHA','')
    if len(runner)!=40:raise RuntimeError('runner source commit must be fixed')
    # The frozen formulas are not allowed to drift from signed R6 preregistration.
    expected={
       'btc_demand_v7/demand_change_v2.py':'eb569c083b42936944da6abf638a0a876febd3f6',
       'btc_demand_v7/episode_quality_v4.py':'1eb05890162dd6f62c91ad99a324a233c6569d3b',
       'btc_demand_v7/v7r3_shadow_worker.py':'b1f3b48297825ecf9384c4f4a48d84a388d64ccb'}
    for name,expected_blob in expected.items():
        actual=call('git','hash-object',name)
        if actual!=expected_blob:raise RuntimeError('frozen mathematical formula changed: '+name)
    if call('git','rev-parse','HEAD')!=runner:
        raise RuntimeError('runner checkout is not the fixed source SHA')
    return runner

def registration(runner):
    return {'schema':'btc-v7r6-live-paired-research-fixed-grid-v1',
            'registered_at_utc':now().isoformat(),
            'research_model_sha':R6_SHA,'frozen_v7r5_sha':R5_SHA,
            'observer_runner_sha':runner,
            'observer_workflow_sha':os.environ['GITHUB_SHA'],
            'source_start_utc':START.isoformat(),'source_end_utc':END.isoformat(),
            'warmup_slots':BASELINE_COUNT,'cadence_minutes':15,
            'eligible_slot_count':7*96-BASELINE_COUNT,
            'source':'independent Cosign verified R5 Binance/OKX already published signed inputs',
            'same_slot_source_and_own_previous_signed_state_required':True,
            'no_backdating_after_due':True,
            'max_commit_deadline_after_anchor_minutes':RECEIPT_DEADLINE_MINUTES,
            'replay_uses_future_prices':False,'trading_authority':False,
            'source_snapshot_signer_identity':R5_ID,
            'observer_identity':R6_ID,
            'never_claim_prospective_skill_from_completed_workflow':True}

def register():
    runner=verify_runner()
    if now()>=START:raise RuntimeError('registration after start refused')
    with tempfile.TemporaryDirectory() as tmp:
        out=pathlib.Path(tmp)/'evidence';clone(out,OUT_BRANCH,create=True)
        reg=registration(runner)
        write(out/'btc_v7r6_evidence','registration.json',reg)
        publish(out,'Freeze before event v7R6 own signed public shadow grid')
        print('BTC_V7R6_LIVE_PRESTART_REKOR_REGISTERED',json.dumps({'runner':runner,'registered':reg['registered_at_utc']}),flush=True)

def valid_r5_snapshot(root,anchor):
    p=root/'slots'/slug(anchor)/'snapshot.json'
    if not p.is_file():return None
    snap=signed(p,R5_ID,R5_SHA)
    if when(snap['anchor_utc'])!=anchor:raise ValueError('wrong R5 slot snapshot')
    rederive(snap)
    anchor_ms=int(anchor.timestamp()*1000)
    one=strict_closed(snap['one_min_rows'],60000,anchor_ms,200)
    five=strict_closed(snap['five_min_rows'],300000,anchor_ms,600)
    if len(one)!=len(snap['one_min_rows']) or len(five)!=len(snap['five_min_rows']):
        raise ValueError('noncausal as-of candle history')
    for k,v in spot_state(one,anchor_ms).items():
        x=float(snap['observation'][k])
        if not(math.isfinite(x) and math.isclose(x,v,rel_tol=1e-11,abs_tol=1e-8)):
            raise ValueError('signed R5 derived spot field differs from raw candles')
    return snap

def decision(current,history,prev_state,issued_at):
    if len(history)!=BASELINE_COUNT or any(s is None for s in history):
        raise ValueError('missing verified R5 history')
    if not current:raise ValueError('no verified contemporaneous R5 source')
    state=state_zero() if prev_state is None else prev_state
    updated,d=advance(state,history,current,issued_utc=issued_at,
                      absolute_consensus_required=True)
    if d.get('calibrated_probability') is not False or updated.get('trading_authority') is not False:
        raise ValueError('research-only invariant violated')
    return updated,d

def run_slot():
    runner=verify_runner()
    t=now();slot=t.replace(minute=(t.minute//15)*15,second=0,microsecond=0)
    if not START<=slot<END:
        print('R6_OUTSIDE_PRECOMMITTED_EPOCH',t.isoformat());return
    i=int((slot-START).total_seconds()//900)
    if i<BASELINE_COUNT:
        print('R6_SIGNED_R5_WARMUP_NOT_ISSUING_ALERT',i);return
    deadline=slot+dt.timedelta(minutes=RECEIPT_DEADLINE_MINUTES)
    if now()>deadline-dt.timedelta(seconds=35):
        raise RuntimeError('missed R6 source window: no backdated candidate')
    with tempfile.TemporaryDirectory() as tmp:
        tmp=pathlib.Path(tmp)
        r5=tmp/'r5';out=tmp/'out';clone(r5,SRC_BRANCH);clone(out,OUT_BRANCH)
        root=r5/'btc_v7r3_evidence';target=out/'btc_v7r6_evidence'
        reg=signed(target/'registration.json',R6_ID,os.environ['GITHUB_SHA'])
        if (reg['observer_runner_sha']!=runner or reg['research_model_sha']!=R6_SHA
            or reg['observer_workflow_sha']!=os.environ['GITHUB_SHA']
            or when(reg['source_start_utc'])!=START or when(reg['source_end_utc'])!=END):
            raise RuntimeError('R6 precommitted registration inconsistent')
        r5reg=signed(root/'registration.json',R5_ID,R5_SHA)
        if r5reg['model_source_sha']!=R5_SHA or when(r5reg['start_utc'])!=START:
            raise RuntimeError('wrong registered R5 epoch')
        record=target/'slots'/slug(slot)/'shadow.json'
        if record.exists():
            signed(record,R6_ID,os.environ['GITHUB_SHA'])
            print('R6_DUPLICATE_SLOT_NO_CHANGE',slug(slot));return
        source_path=root/'slots'/slug(slot)/'signal.json'
        while not source_path.exists() and now()<deadline-dt.timedelta(minutes=2):
            time.sleep(15)
            call('git','pull','--ff-only','origin',SRC_BRANCH,cwd=r5)
        if not source_path.exists():raise RuntimeError('no signed R5 signal in decision window')
        base=signed(source_path,R5_ID,R5_SHA)
        if base.get('status')!='SIGNED_STATE_PUBLISHED' or base.get('slot_id')!=slug(slot):
            raise RuntimeError('source R5 has no usable signed forecast')
        anchors=[slot-dt.timedelta(minutes=15*j) for j in reversed(range(1,BASELINE_COUNT+1))]
        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
            hist=list(pool.map(lambda x:valid_r5_snapshot(root,x),anchors))
        current=valid_r5_snapshot(root,slot)
        if source_hash(current)!=base['diagnostic']['current_snapshot_sha256']:
            raise RuntimeError('source signed state not bound to same input snapshot')
        if i==BASELINE_COUNT:
            previous=None
        else:
            previous_path=target/'slots'/slug(slot-dt.timedelta(minutes=15))/'shadow.json'
            if not previous_path.exists():raise RuntimeError('missing previous signed R6 state: never reset chain')
            prev=signed(previous_path,R6_ID,os.environ['GITHUB_SHA'])
            if prev.get('kind')!='R6_SIGNED_SHADOW' or prev['slot_id']!=slug(slot-dt.timedelta(minutes=15)):
                raise RuntimeError('invalid previous R6 state')
            previous=prev['challenger_state']
        issued=now()
        state,diag=decision(current,hist,previous,issued)
        if issued>deadline-dt.timedelta(seconds=35):
            raise RuntimeError('signal computation too late; do not sign')
        payload={'schema':'btc-v7r6-paired-future-public-shadow-v1',
                 'kind':'R6_SIGNED_SHADOW','slot_id':slug(slot),'anchor_utc':slot.isoformat(),
                 'decision_computed_utc':issued.isoformat(),
                 'source_r5_signal_sha256':sha(base),
                 'source_r5_snapshot_sha256':source_hash(current),
                 'research_model_sha':R6_SHA,'runner_sha':runner,
                 'baseline_r5_diagnostic':base['diagnostic'],
                 'challenger_diagnostic':diag,'challenger_state':state,
                 'not_a_verified_public_release_time':True,
                 'trade_skill_proven':False,'trading_authority':False}
        write(record.parent,'shadow.json',payload)
        if now()>deadline-dt.timedelta(seconds=10):
            raise RuntimeError('missed publication deadline after signing; do not push')
        publish(out,'BTC R6 prospective shadow '+slug(slot))
        print('R6_PROSPECTIVE_SHADOW_PUBLISHED',slug(slot),'up',diag.get('alert'),'UTC',now().isoformat(),flush=True)

if __name__=='__main__':
    import sys
    if len(sys.argv)!=2 or sys.argv[1] not in ('register','slot'):
        raise SystemExit('usage: python -m btc_demand_v7.v7r6_live_pair_worker register|slot')
    (register if sys.argv[1]=='register' else run_slot)()
