"""Frozen signed forecasts and rolling outcome checks for an uncertainty component.

This is not the complete user-requested trading system. Readiness stays false.
"""
import argparse,datetime as dt,hashlib,json,os,pathlib,tempfile,time
import numpy as np
from joblib import load
import forecast as f
import conditional_path as c
from add_regime import regime
from market_history import long_tail,fetch,API
from robust_distribution_check import har_features,ewma_from_raw,KINDS
from btc_core_observer.collector import call,canonical
from btc_core_observer.sigstore_verify import Verifier

UTC=dt.timezone.utc
REPO='sergeytren1984-ux/neora-b2b-v2-clean'
SOURCE='btc-core-distribution-forward-20261013'
LEDGER='btc-core-distribution-evidence-20261013'
WORKFLOW='btc-v7r3-signed-demand-shadow.yml'
IDENTITY=f'https://github.com/{REPO}/.github/workflows/{WORKFLOW}@refs/heads/{SOURCE}'
ISSUER='https://token.actions.githubusercontent.com'
START=dt.datetime(2026,10,13,11,30,tzinfo=UTC)
END=dt.datetime(2026,10,20,11,30,tzinfo=UTC)
ASSESSMENT_END=END+dt.timedelta(hours=72)
DEADLINE=dt.timedelta(minutes=10)

def now():return dt.datetime.now(UTC)
def slug(t):return t.strftime('%Y%m%dT%H%MZ')
def digest(obj):return hashlib.sha256(canonical(obj)).hexdigest()

def model():
    root=pathlib.Path('btc_core_forecast/runtime');manifest=json.loads((root/'manifest.json').read_text())
    blob=root/'distribution.joblib'
    if hashlib.sha256(blob.read_bytes()).hexdigest()!=manifest['model_sha256']:raise ValueError('frozen model hash mismatch')
    if manifest['trading_authority'] is not False or manifest['full_system_ready'] is not False:raise ValueError('invalid readiness claim')
    return load(blob),manifest

def predict(anchor,cache):
    m,manifest=model();ts=int(anchor.timestamp()*1000)
    if ts<f.stamp(manifest['training_input_end_utc']):raise ValueError('model was not available as of requested anchor')
    t,a,archives,rawsha=long_tail(ts,cache,frozen_archives=manifest['archives'])
    x,sigma=f.feature(a,len(a)-1,ts);x=np.r_[x,regime(a,len(a)-1)]
    paths,high,low=c.distribution(m,x,sigma)
    current={'vol24':1.,'vol1':x[5]/sigma,'vol4':x[9]/sigma}
    ema=ewma_from_raw(str(pathlib.Path(cache)/'assembled.json.gz'),np.array([len(a)-1]))
    current.update({k:v[0]/sigma for k,v in ema.items()})
    scenarios={'candidate':paths};extrema={'candidate':(high,low)}
    for kind,ratio in current.items():
        scale=(ratio/np.maximum(m['calibration_ratios'][kind],1e-8))[:,None]*sigma
        scenarios[kind]=m['close']*scale;extrema[kind]=(m['high']*scale,m['low']*scale)
    hm=dict(m,calibration_logs=m['har_calibration_logs'])
    hx=har_features(x[None],np.array([sigma]))
    hlogs=np.array([head.predict(hx)[0] for head in m['har_heads']])
    hc,hh,hl=c.distribution(hm,x,sigma,hlogs);scenarios['har']=hc;extrema['har']=(hh,hl)
    spot=float(a[-1,4]);forecasts={}
    for hours,barrier in ((1,.007),(4,.012),(24,.02)):
        p=spot*np.exp(paths[:,hours-1]);r=paths[:,hours-1]
        forecasts[str(hours)]={'медиана':float(np.median(p)),'нижняя_граница_80проц':float(np.quantile(p,.1)),
            'верхняя_граница_80проц':float(np.quantile(p,.9)),
            'вероятность_роста':float(np.mean(r>=np.log1p(barrier))),
            'вероятность_снижения':float(np.mean(r<=np.log1p(-barrier))),
            'вероятность_малого_изменения':float(np.mean((r>np.log1p(-barrier))&(r<np.log1p(barrier)))),
            'порог_проц':100*barrier}
    competing={}
    for kind,(upper,lower) in extrema.items():
        competing[kind]={}
        for hours in (24,48,72):
            classes=f.first_passage(upper,lower,hours=hours)
            competing[kind][str(hours)]=(np.bincount(classes,minlength=4)/len(classes)).tolist()
    bridge=a[a[:,0]>=f.stamp('2026-10-12T00:00:00Z')]
    return {'schema':'btc-uncertainty-component-forecast-v1','kind':'FORECAST',
        'source_sha':os.environ.get('GITHUB_SHA'),'anchor_utc':anchor.isoformat(),
        'asof_МСК':anchor.astimezone(dt.timezone(dt.timedelta(hours=3))).isoformat(),
        'computed_at_utc':now().isoformat(),'model_sha256':manifest['model_sha256'],
        'reference_spot':spot,'features':x.tolist(),'past_sigma':sigma,'input_hash':rawsha,
        'archive_provenance':archives,'bridge_numeric_rows':bridge.tolist(),
        'forecast_рус':forecasts,'barrier_order_probabilities':competing,
        'samples_log_returns':{kind:{str(h):v[:,h-1].tolist() for h in (1,4,24)} for kind,v in scenarios.items()},
        'scope':'spot uncertainty component; excludes R6, macro and OTC action authority',
        'trading_authority':False,'full_system_ready':False,'prospective_skill_proven':False,
        'actual_public_release_time_independently_proven':False,'core_action':'BLOCKED_NOT_PROVEN'}

def clone(tmp):
    root=pathlib.Path(tmp)/'ledger';call('gh','auth','setup-git');remote='https://github.com/'+REPO+'.git'
    if call('git','ls-remote','--heads',remote,LEDGER):call('git','clone','--quiet','--depth','1','--branch',LEDGER,remote,str(root))
    else:
        root.mkdir();call('git','init','--quiet',cwd=root);call('git','checkout','--quiet','-b',LEDGER,cwd=root);call('git','remote','add','origin',remote,cwd=root)
    call('git','config','user.name','btc-distribution-observer',cwd=root);call('git','config','user.email','btc-distribution-observer@users.noreply.github.com',cwd=root)
    return root

def publish(root):
    call('git','add','distribution_records',cwd=root);call('git','commit','--quiet','-m','Signed forecast/outcome component record',cwd=root)
    for attempt in range(3):
        try:
            if attempt:call('git','pull','--quiet','--rebase','origin',LEDGER,cwd=root)
            call('git','push','--quiet','origin','HEAD:refs/heads/'+LEDGER,cwd=root);return
        except RuntimeError:
            if attempt==2:raise

def signed(root,relative,payload,v,sha):
    path=root/'distribution_records'/relative
    if path.exists():raise RuntimeError('immutable record collision')
    path.parent.mkdir(exist_ok=True,parents=True);path.write_bytes(canonical(payload))
    call('cosign','sign-blob','--yes','--bundle',str(path)+'.sigstore.json',str(path),env=dict(os.environ,TUF_ROOT=str(v.root.parent)))
    v.verify(path,IDENTITY,ISSUER,sha)
    return path

def verify_read(path,v,sha):
    v.verify(path,IDENTITY,ISSUER,sha);return json.loads(path.read_text())

def outcome(record,hours):
    import urllib.parse
    anchor=f.stamp(record['anchor_utc']);end=anchor+hours*3600000
    if end>int(now().timestamp()*1000)//300000*300000:raise ValueError('outcome not closed')
    query=urllib.parse.urlencode({'symbol':'BTCUSDT','interval':'5m','startTime':anchor,'endTime':end-1,'limit':1000})
    rows=json.loads(fetch(API+'?'+query))
    if len(rows)!=hours*12 or int(rows[0][0])!=anchor or int(rows[-1][6])+1!=end:raise ValueError('incomplete outcome grid')
    for i,r in enumerate(rows):
        if int(r[0])!=anchor+i*300000 or int(r[6])+1!=int(r[0])+300000:raise ValueError('outcome grid gap')
        op,hi,lo,cl=map(float,r[1:5])
        if not np.isfinite([op,hi,lo,cl]).all() or not 0<lo<=min(op,cl)<=max(op,cl)<=hi:raise ValueError('invalid outcome OHLC')
    truth=float(rows[-1][4]);spot=record['reference_spot'];scores={}
    if hours in (1,4,24):
        barrier={1:.007,4:.012,24:.02}[hours];actual_return=np.log(truth/spot)
        trueclass=0 if actual_return>=np.log1p(barrier) else (1 if actual_return<=np.log1p(-barrier) else 2)
        for kind,heads in record['samples_log_returns'].items():
            returns=np.array(heads[str(hours)]);prices=spot*np.exp(returns);lo,mid,hi=np.quantile(prices,[.1,.5,.9])
            probs=np.array([(returns>=np.log1p(barrier)).mean(),(returns<=np.log1p(-barrier)).mean(),((returns>np.log1p(-barrier))&(returns<np.log1p(barrier))).mean()])
            scores[kind]={'crps':f.crps(prices,truth),'mae':float(abs(mid-truth)),'coverage_80pct':bool(lo<=truth<=hi),'brier':float(np.sum((probs-np.eye(3)[trueclass])**2))}
    if hours in (24,48,72):
        highs=np.array([float(r[2]) for r in rows]).reshape(hours,12).max(1)
        lows=np.array([float(r[3]) for r in rows]).reshape(hours,12).min(1)
        actual_class=f.first_passage(np.log(highs[None]/spot),np.log(lows[None]/spot),hours=hours)[0]
        for kind,heads in record['barrier_order_probabilities'].items():
            probabilities=np.array(heads[str(hours)]);scores.setdefault(kind,{})['barrier_brier']=float(np.sum((probabilities-np.eye(4)[actual_class])**2))
    return {'schema':'btc-uncertainty-component-outcome-v1','anchor_utc':record['anchor_utc'],'horizon_hours':hours,
        'forecast_sha256':digest(record),'received_at_utc':now().isoformat(),'outcome_rows':rows,'scores':scores,
        'trading_authority':False,'full_system_ready':False,'prospective_skill_proven':False}

def watch(minutes=85):
    sha=os.environ['GITHUB_SHA']
    if os.environ.get('GITHUB_REF')!='refs/heads/'+SOURCE:raise RuntimeError('wrong source ref')
    if now()>=ASSESSMENT_END:return
    stop=min(now()+dt.timedelta(minutes=minutes),ASSESSMENT_END)
    with tempfile.TemporaryDirectory() as tmp:
        root=clone(tmp);v=Verifier('cosign',pathlib.Path(tmp)/'trust');v.initialize()
        _,manifest=model();regpath=root/'distribution_records/registration.json'
        if not regpath.exists():
            if now()>=START:raise RuntimeError('registration after START refused')
            reg={'schema':'btc-distribution-fixed-future-grid-v1','registered_at_utc':now().isoformat(),
                'source_sha':sha,'start_utc':START.isoformat(),'end_utc':END.isoformat(),'assessment_end_utc':ASSESSMENT_END.isoformat(),'hourly_slots':168,
                'manifest':manifest,'purpose':'prospective component measurements, not full-system trading admission',
                'model_changes_allowed':False,'missing_slots_remain_in_denominator':True,
                'trading_authority':False,'full_system_ready':False,'prospective_skill_proven':False}
            signed(root,'registration.json',reg,v,sha);publish(root)
        reg=verify_read(regpath,v,sha)
        if reg['source_sha']!=sha or reg['manifest']!=manifest or reg['start_utc']!=START.isoformat():raise ValueError('frozen registration mismatch')
        verified={}
        print('DISTRIBUTION_COMPONENT_REGISTERED',START.isoformat(),END.isoformat(),flush=True)
        while now()<stop:
            at=START
            while at<=now() and at<END:
                relative='slots/'+slug(at)+'/prediction.json';path=root/'distribution_records'/relative
                if not path.exists():
                    if now()>at+DEADLINE:
                        record={'kind':'MISSING_NOT_BACKFILLED','anchor_utc':at.isoformat(),'recorded_at_utc':now().isoformat(),'trading_authority':False,'full_system_ready':False}
                    else:
                        try:record=predict(at,pathlib.Path(tmp)/'archive_cache')
                        except Exception as exc:record={'kind':'FORECAST_FAILED','anchor_utc':at.isoformat(),'recorded_at_utc':now().isoformat(),'error':type(exc).__name__,'trading_authority':False,'full_system_ready':False}
                    if record['kind']=='FORECAST' and now()>at+DEADLINE:raise RuntimeError('forecast missed deadline')
                    signed(root,relative,record,v,sha)
                    if record['kind']=='FORECAST' and now()>at+DEADLINE:raise RuntimeError('signing missed deadline')
                    publish(root);print('COMPONENT_SLOT',slug(at),record['kind'],flush=True)
                at+=dt.timedelta(hours=1)
            for path in sorted((root/'distribution_records/slots').glob('*/prediction.json')):
                if str(path) not in verified:verified[str(path)]=verify_read(path,v,sha)
                record=verified[str(path)]
                if record['kind']!='FORECAST':continue
                for hours in (1,4,24,48,72):
                    relative='slots/'+path.parent.name+'/outcome_'+str(hours)+'h.json'
                    if (root/'distribution_records'/relative).exists() or now().timestamp()*1000<f.stamp(record['anchor_utc'])+hours*3600000:continue
                    try:payload=outcome(record,hours)
                    except Exception as ex:print('OUTCOME_FETCH_RETRY',path.parent.name,hours,type(ex).__name__,flush=True);continue
                    signed(root,relative,payload,v,sha);publish(root);print('COMPONENT_OUTCOME',path.parent.name,hours,flush=True)
            time.sleep(min(30,max(0,(stop-now()).total_seconds())))

def relay():
    if now()>=ASSESSMENT_END:return
    call('gh','api','--method','POST',f'repos/{REPO}/actions/workflows/{WORKFLOW}/dispatches','-f','ref='+SOURCE,'-f','inputs[action]=forecast')

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['watch','relay','preflight']);args=parser.parse_args()
    if args.action=='watch':watch()
    elif args.action=='relay':relay()
    else:
        anchor=now().replace(second=0,microsecond=0);anchor-=dt.timedelta(minutes=anchor.minute%5)
        record=predict(anchor,'inputs/deployment_archives');record['excluded_from_future_grid']=True
        f.write('btc_core_forecast/runtime/preflight.json',record)
        print('REAL_COMPONENT_PREFLIGHT',record['anchor_utc'],record['reference_spot'],'full_system_ready',record['full_system_ready'],flush=True)
