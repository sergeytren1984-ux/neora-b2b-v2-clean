"""Frozen macro source, separate from unqualified price/trading forecasts."""
import datetime as dt,json,os,pathlib,tempfile,time
from pinned_macro_capture import collect
from btc_core_observer.collector import call,canonical
from btc_core_observer.sigstore_verify import Verifier
UTC=dt.timezone.utc
REPO='sergeytren1984-ux/neora-b2b-v2-clean'
SOURCE='btc-core-macro-source-20261013';LEDGER='btc-core-macro-evidence-20261013'
WORKFLOW='btc-v7r3-signed-demand-shadow.yml'
IDENTITY=f'https://github.com/{REPO}/.github/workflows/{WORKFLOW}@refs/heads/{SOURCE}'
ISSUER='https://token.actions.githubusercontent.com'
START=dt.datetime(2026,10,13,18,tzinfo=UTC);END=dt.datetime(2026,10,20,11,30,tzinfo=UTC)
def now():return dt.datetime.now(UTC)
def slug(t):return t.strftime('%Y%m%dT%H%MZ')

def ledger(tmp):
    root=pathlib.Path(tmp)/'ledger';call('gh','auth','setup-git');remote='https://github.com/'+REPO+'.git'
    if call('git','ls-remote','--heads',remote,LEDGER):call('git','clone','--quiet','--depth','1','--branch',LEDGER,remote,str(root))
    else:
        root.mkdir();call('git','init','--quiet',cwd=root);call('git','checkout','--quiet','-b',LEDGER,cwd=root);call('git','remote','add','origin',remote,cwd=root)
    call('git','config','user.name','btc-pinned-macro',cwd=root);call('git','config','user.email','btc-pinned-macro@users.noreply.github.com',cwd=root);return root

def publish(root):
    call('git','add','macro_records',cwd=root);call('git','commit','--quiet','-m','Signed fixed-source macro receipts',cwd=root)
    for i in range(3):
        try:
            if i:call('git','pull','--quiet','--rebase','origin',LEDGER,cwd=root)
            call('git','push','--quiet','origin','HEAD:refs/heads/'+LEDGER,cwd=root);return
        except RuntimeError:
            if i==2:raise

def sign(root,name,payload,v,sha):
    p=root/'macro_records'/name
    if p.exists():raise ValueError('immutable record already exists')
    p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(canonical(payload))
    call('cosign','sign-blob','--yes','--bundle',str(p)+'.sigstore.json',str(p),env=dict(os.environ,TUF_ROOT=str(v.root.parent)))
    v.verify(p,IDENTITY,ISSUER,sha);publish(root)

def watch():
    sha=os.environ['GITHUB_SHA']
    if os.environ.get('GITHUB_REF')!='refs/heads/'+SOURCE:raise ValueError('wrong source branch')
    if now()>=END:return
    stop=min(now()+dt.timedelta(minutes=85),END)
    with tempfile.TemporaryDirectory() as tmp:
        root=ledger(tmp);v=Verifier('cosign',pathlib.Path(tmp)/'trust');v.initialize();regpath=root/'macro_records/registration.json'
        if not regpath.exists():
            if now()>=START:raise ValueError('preregistration after start forbidden')
            reg={'schema':'btc-fixed-macro-grid-v1','source_sha':sha,'registered_at_utc':now().isoformat(),
                'start_utc':START.isoformat(),'end_exclusive_utc':END.isoformat(),'cadence_minutes':15,
                'due_slots':int((END-START).total_seconds()/900),'capture_deadline_minutes':12,
                'actual_checkout':'github.sha, no mutable collector branch','quote_symbols':['DX-Y.NYB','NQ=F','^TNX'],
                'calendar':'official BLS receipt; no consensus or release-surprise imputation',
                'full_system_ready':False,'trading_authority':False}
            sign(root,'registration.json',reg,v,sha)
        v.verify(regpath,IDENTITY,ISSUER,sha);reg=json.loads(regpath.read_text())
        if reg['source_sha']!=sha or reg['start_utc']!=START.isoformat():raise ValueError('frozen source registration changed')
        if now()<START and not (root/'macro_records/preflight.json').exists():
            p=collect();p.update(excluded_from_fixed_grid=True,source_sha=sha);sign(root,'preflight.json',p,v,sha)
        cursor=START
        while now()<stop:
            while cursor<=now() and cursor<END:
                name='slots/'+slug(cursor)+'/record.json'
                if not (root/'macro_records'/name).exists():
                    if now()>cursor+dt.timedelta(minutes=12):payload={'kind':'MISSING_NOT_BACKFILLED','anchor_utc':cursor.isoformat(),'full_system_ready':False,'trading_authority':False}
                    else:
                        payload=collect();payload.update(kind='MACRO_CAPTURED',anchor_utc=cursor.isoformat(),source_sha=sha)
                        if now()>cursor+dt.timedelta(minutes=12):raise ValueError('macro capture deadline exceeded')
                    sign(root,name,payload,v,sha);print('MACRO_SLOT',slug(cursor),payload['kind'],flush=True)
                cursor+=dt.timedelta(minutes=15)
            time.sleep(min(15,max(0,(stop-now()).total_seconds())))

def relay():
    if now()<END:call('gh','api','--method','POST',f'repos/{REPO}/actions/workflows/{WORKFLOW}/dispatches','-f','ref='+SOURCE,'-f','inputs[action]=forecast')

if __name__=='__main__':
    import sys
    if sys.argv[1:]==['watch']:watch()
    elif sys.argv[1:]==['relay']:relay()
    else:raise SystemExit('watch|relay')
