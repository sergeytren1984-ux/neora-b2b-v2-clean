"""Minute price health measurements; this guard is not a price forecaster."""
import datetime as dt,json,os,pathlib,tempfile,time
from btc_demand_v7.live_snapshot import json_get,SOURCE_SPOT
from btc_core_forecast.impulse_check import inspect
from btc_core_observer.collector import call,canonical
from btc_core_observer.sigstore_verify import Verifier

UTC=dt.timezone.utc
REPO='sergeytren1984-ux/neora-b2b-v2-clean'
SOURCE='btc-core-live-quality-20261013'
LEDGER='btc-core-live-quality-evidence-20261013'
WORKFLOW='btc-v7r3-signed-demand-shadow.yml'
IDENTITY=f'https://github.com/{REPO}/.github/workflows/{WORKFLOW}@refs/heads/{SOURCE}'
ISSUER='https://token.actions.githubusercontent.com'
START=dt.datetime(2026,10,13,12,15,tzinfo=UTC)
END=dt.datetime(2026,10,20,11,30,tzinfo=UTC)

def now():return dt.datetime.now(UTC)
def slug(t):return t.strftime('%Y%m%dT%H%MZ')

def clone(tmp):
    root=pathlib.Path(tmp)/'ledger';call('gh','auth','setup-git');remote='https://github.com/'+REPO+'.git'
    if call('git','ls-remote','--heads',remote,LEDGER):call('git','clone','--quiet','--depth','1','--branch',LEDGER,remote,str(root))
    else:
        root.mkdir();call('git','init','--quiet',cwd=root);call('git','checkout','--quiet','-b',LEDGER,cwd=root);call('git','remote','add','origin',remote,cwd=root)
    call('git','config','user.name','btc-price-health',cwd=root);call('git','config','user.email','btc-price-health@users.noreply.github.com',cwd=root)
    return root

def publish(root):
    call('git','add','price_health',cwd=root);call('git','commit','--quiet','-m','Signed fresh price health record',cwd=root)
    for attempt in range(3):
        try:
            if attempt:call('git','pull','--quiet','--rebase','origin',LEDGER,cwd=root)
            call('git','push','--quiet','origin','HEAD:refs/heads/'+LEDGER,cwd=root);return
        except RuntimeError:
            if attempt==2:raise

def signed(root,relative,payload,v,sha):
    path=root/'price_health'/relative
    if path.exists():raise ValueError('immutable record collision')
    path.parent.mkdir(exist_ok=True,parents=True);path.write_bytes(canonical(payload))
    call('cosign','sign-blob','--yes','--bundle',str(path)+'.sigstore.json',str(path),env=dict(os.environ,TUF_ROOT=str(v.root.parent)))
    v.verify(path,IDENTITY,ISSUER,sha)

def collect(at):
    anchor=int(at.timestamp()*1000);begin=now()
    rows=json_get(SOURCE_SPOT,{'symbol':'BTCUSDT','interval':'1m','endTime':anchor-1,'limit':16},timeout=15)
    received=now();out=inspect(rows,anchor,int(received.timestamp()*1000))
    out.update(kind='OBSERVED_PRICE_HEALTH',source_sha=os.environ.get('GITHUB_SHA'),request_started_utc=begin.isoformat(),
        computed_utc=now().isoformat(),raw_minute_rows=rows,source=SOURCE_SPOT,
        not_a_replacement_for_predictive_model=True,predictive_skill_proven=False)
    return out

def watch():
    sha=os.environ['GITHUB_SHA']
    if os.environ.get('GITHUB_REF')!='refs/heads/'+SOURCE:raise ValueError('wrong fixed source ref')
    if now()>=END:return
    stop=min(now()+dt.timedelta(minutes=85),END)
    with tempfile.TemporaryDirectory() as tmp:
        root=clone(tmp);v=Verifier('cosign',pathlib.Path(tmp)/'trust');v.initialize();regpath=root/'price_health/registration.json'
        if not regpath.exists():
            if now()>=START:raise ValueError('preregistration after START refused')
            reg={'schema':'btc-minute-health-fixed-grid-v1','registered_utc':now().isoformat(),'source_sha':sha,
                'start_utc':START.isoformat(),'end_exclusive_utc':END.isoformat(),'cadence_seconds':60,
                'due_slots':int((END-START).total_seconds()/60),'purpose':'fresh movement recognition, not prediction or trade admission',
                'thresholds':{'move_or_range_6m_usdt':500,'move_or_range_15m_usdt':1000},
                'capture_deadline_seconds':45,'no_backfill':True,'trading_authority':False,'full_system_ready':False}
            signed(root,'registration.json',reg,v,sha);publish(root)
        v.verify(regpath,IDENTITY,ISSUER,sha);reg=json.loads(regpath.read_text())
        if reg['source_sha']!=sha or reg['start_utc']!=START.isoformat() or reg['end_exclusive_utc']!=END.isoformat():raise ValueError('frozen registration mismatch')
        cursor=START
        print('MINUTE_HEALTH_REGISTERED',START.isoformat(),flush=True)
        while now()<stop:
            while cursor<=now() and cursor<END:
                name='slots/'+slug(cursor)+'/record.json';path=root/'price_health'/name
                if not path.exists():
                    if now()>cursor+dt.timedelta(seconds=45):record={'kind':'MISSING_NOT_BACKFILLED','anchor_utc':cursor.isoformat(),'recorded_utc':now().isoformat(),'trading_authority':False,'full_system_ready':False}
                    else:
                        try:record=collect(cursor)
                        except Exception as ex:record={'kind':'SOURCE_UNAVAILABLE','anchor_utc':cursor.isoformat(),'recorded_utc':now().isoformat(),'error':type(ex).__name__,'trading_authority':False,'full_system_ready':False}
                    if record['kind']=='OBSERVED_PRICE_HEALTH' and now()>cursor+dt.timedelta(seconds=45):raise ValueError('minute capture deadline missed')
                    signed(root,name,record,v,sha);publish(root);print('MINUTE_HEALTH',slug(cursor),record['kind'],record.get('state_рус'),flush=True)
                cursor+=dt.timedelta(minutes=1)
            time.sleep(min(10,max(0,(stop-now()).total_seconds())))

def relay():
    if now()<END:call('gh','api','--method','POST',f'repos/{REPO}/actions/workflows/{WORKFLOW}/dispatches','-f','ref='+SOURCE,'-f','inputs[action]=forecast')

if __name__=='__main__':
    import sys
    if sys.argv[1:] not in (['watch'],['relay']):raise SystemExit('watch|relay')
    (watch if sys.argv[1]=='watch' else relay)()
