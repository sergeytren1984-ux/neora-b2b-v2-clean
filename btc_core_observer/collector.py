"""Bounded, signed forward market archive. No forecasts or trade authority."""
import argparse,datetime as dt,hashlib,json,os,pathlib,subprocess,tempfile,time
from btc_demand_v7.live_snapshot import collect
from btc_core_observer.sigstore_verify import Verifier

UTC=dt.timezone.utc
REPO='sergeytren1984-ux/neora-b2b-v2-clean'
SOURCE='btc-core-forward-source-20261013'
LEDGER='btc-core-forward-raw-20261013'
WORKFLOW='btc-v7r3-signed-demand-shadow.yml'
IDENTITY=f'https://github.com/{REPO}/.github/workflows/{WORKFLOW}@refs/heads/{SOURCE}'
ISSUER='https://token.actions.githubusercontent.com'
START=dt.datetime(2026,10,13,11,0,tzinfo=UTC)
END=dt.datetime(2026,10,14,11,0,tzinfo=UTC)
CADENCE=dt.timedelta(minutes=15)

def now():return dt.datetime.now(UTC)
def when(s):
    t=dt.datetime.fromisoformat(s.replace('Z','+00:00'))
    if t.tzinfo is None:raise ValueError('timezone required')
    return t.astimezone(UTC)
def canonical(x):return (json.dumps(x,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode()
def digest(x):return hashlib.sha256(canonical(x)).hexdigest()
def slug(t):return t.strftime('%Y%m%dT%H%MZ')
def call(*args,cwd=None,env=None):
    p=subprocess.run(args,cwd=cwd,env=env,capture_output=True,text=True,timeout=90)
    if p.returncode:raise RuntimeError('command failed '+str(args[0])+': '+p.stderr[-700:])
    return p.stdout.strip()

def ledger(tmp):
    p=pathlib.Path(tmp)/'ledger';call('gh','auth','setup-git')
    remote='https://github.com/'+REPO+'.git'
    existing=call('git','ls-remote','--heads',remote,LEDGER)
    if existing:call('git','clone','--quiet','--depth','1','--branch',LEDGER,remote,str(p))
    else:
        p.mkdir();call('git','init','--quiet',cwd=p);call('git','checkout','--quiet','-b',LEDGER,cwd=p)
        call('git','remote','add','origin',remote,cwd=p)
    call('git','config','user.name','btc-core-forward-data',cwd=p)
    call('git','config','user.email','btc-core-forward-data@users.noreply.github.com',cwd=p)
    return p

def publish(root,message):
    call('git','add','core_raw',cwd=root);call('git','commit','--quiet','-m',message,cwd=root)
    for n in range(3):
        try:
            if n:call('git','pull','--quiet','--rebase','origin',LEDGER,cwd=root)
            call('git','push','--quiet','origin','HEAD:refs/heads/'+LEDGER,cwd=root);return
        except RuntimeError:
            if n==2:raise

def signed_write(root,relative,obj,verifier,source_sha):
    p=root/'core_raw'/relative
    if p.exists():raise RuntimeError('immutable record exists')
    p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(canonical(obj))
    env=dict(os.environ,TUF_ROOT=str(verifier.root.parent))
    call('cosign','sign-blob','--yes','--bundle',str(p)+'.sigstore.json',str(p),env=env)
    verifier.verify(p,IDENTITY,ISSUER,source_sha)
    return p

def read_verified(path,v,sha):
    v.verify(path,IDENTITY,ISSUER,sha);return json.loads(path.read_text())

def registration(source_sha):
    if now()>=START:raise RuntimeError('cannot preregister after start')
    return {'schema':'btc-core-forward-data-fixed-grid-v1','registered_at_utc':now().isoformat(),
        'source_sha':source_sha,'source_branch':SOURCE,'identity':IDENTITY,'start_utc':START.isoformat(),
        'end_exclusive_utc':END.isoformat(),'cadence_minutes':15,'due_slots':96,
        'purpose':'contemporaneous raw dataset, not model validation or a trading signal',
        'spot_1m_5m':'REQUIRED','OKX_oi_book_funding':'OPTIONAL_WITH_EXPLICIT_MISSING',
        'OKX_not_inserted_into_Binance_training_features':True,'never_backfill_missed_live_factors':True,
        'capture_deadline_minutes':12,'actual_public_release_time_independently_proven':False,
        'historical_candidates_deployed':False,'trading_authority':False,'predictive_skill_proven':False}

def due_missing_or_current(t,registered_start=START):
    return registered_start<=t<END and t.minute%15==0 and t.second==0 and t.microsecond==0

def watch(minutes=90):
    sha=os.environ['GITHUB_SHA']
    if os.environ.get('GITHUB_REF')!='refs/heads/'+SOURCE:raise RuntimeError('wrong observer ref')
    if now()>=END:print('FORWARD_EPOCH_ENDED',flush=True);return
    stop=min(now()+dt.timedelta(minutes=minutes),END)
    with tempfile.TemporaryDirectory() as tmp:
        root=ledger(tmp);v=Verifier('cosign',pathlib.Path(tmp)/'trust');v.initialize()
        regpath=root/'core_raw/registration.json'
        if not regpath.exists():
            signed_write(root,'registration.json',registration(sha),v,sha);publish(root,'Preregister bounded core data grid before START')
        reg=read_verified(regpath,v,sha)
        if reg['source_sha']!=sha or when(reg['start_utc'])!=START or when(reg['end_exclusive_utc'])!=END:
            raise RuntimeError('source or fixed epoch changed')
        print('CORE_FORWARD_REGISTERED',sha,START.isoformat(),END.isoformat(),flush=True)
        # One explicit preflight before the declared epoch, not counted in the grid.
        if now()<START and not (root/'core_raw/preflight.json').exists():
            anchor=now().replace(minute=(now().minute//5)*5,second=0,microsecond=0)
            try:
                snap=collect(int(anchor.timestamp()*1000))
                payload={'schema':'btc-core-forward-preflight-v1','excluded_from_fixed_grid':True,'snapshot':snap,'trading_authority':False}
            except Exception as ex:payload={'schema':'btc-core-forward-preflight-v1','excluded_from_fixed_grid':True,'failure':type(ex).__name__,'trading_authority':False}
            signed_write(root,'preflight.json',payload,v,sha);publish(root,'Signed preflight only, not prospective model evidence')
            print('CORE_PREFLIGHT_PUBLISHED',payload.get('failure','RAW_AVAILABLE'),flush=True)
        while now()<stop:
            t=now();slot=t.replace(minute=(t.minute//15)*15,second=0,microsecond=0)
            path='slots/'+slug(slot)+'/record.json'
            if due_missing_or_current(slot) and not (root/'core_raw'/path).exists():
                if t>slot+dt.timedelta(minutes=12):
                    record={'schema':'btc-core-forward-slot-v1','kind':'MISSING_NOT_BACKFILLED','anchor_utc':slot.isoformat(),'recorded_at_utc':t.isoformat(),'trading_authority':False}
                else:
                    try:
                        snap=collect(int(slot.timestamp()*1000))
                        if now()>slot+dt.timedelta(minutes=12):raise RuntimeError('capture deadline missed')
                        record={'schema':'btc-core-forward-slot-v1','kind':'RAW_CAPTURED','anchor_utc':slot.isoformat(),
                            'captured_at_utc':now().isoformat(),'snapshot_sha256':digest(snap),'snapshot':snap,
                            'prediction_issued':False,'trading_authority':False}
                    except Exception as ex:
                        record={'schema':'btc-core-forward-slot-v1','kind':'CAPTURE_FAILED','anchor_utc':slot.isoformat(),
                            'recorded_at_utc':now().isoformat(),'error':type(ex).__name__,'trading_authority':False}
                signed_write(root,path,record,v,sha);publish(root,'Core forward raw slot '+slug(slot))
                print('CORE_RAW_SLOT_PUBLISHED',slug(slot),record['kind'],flush=True)
            time.sleep(min(30,max(0,(stop-now()).total_seconds())))

def relay():
    if now()>=END:print('NO_RELAY_AFTER_END',flush=True);return
    # Exact fixed source branch; dispatcher already exists in default branch.
    call('gh','api','--method','POST',f'repos/{REPO}/actions/workflows/{WORKFLOW}/dispatches',
         '-f','ref='+SOURCE,'-f','inputs[action]=forecast')
    print('NEXT_BOUNDED_FORWARD_CHUNK_REQUESTED',flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['watch','relay']);p.add_argument('--minutes',type=int,default=90);a=p.parse_args()
    if not 1<=a.minutes<=90:raise ValueError('chunk bound exceeded')
    (relay if a.action=='relay' else lambda:watch(a.minutes))()
