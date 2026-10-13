"""Freeze a current research distribution model and matched baselines."""
import argparse,gzip,hashlib,json,pathlib
import numpy as np
from joblib import dump
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
import forecast as f
import conditional_path as c
import walkforward as w
from add_regime import regime
from market_history import long_tail
from robust_distribution_check import har_features,ewma_from_raw

def main(output='btc_core_forecast/runtime'):
    out=pathlib.Path(output)
    if (out/'distribution.joblib').exists():raise RuntimeError('frozen model exists; use a new explicit output directory and a new future epoch')
    provenance=json.loads(pathlib.Path('inputs/deployment_tail_provenance.json').read_text());anchor=provenance['anchor']
    with gzip.open('inputs/spot_2024_2026H1.json.gz','rt') as stream:base=json.load(stream)
    t,a,archives,rawsha=long_tail(anchor,'inputs/deployment_archives',base,provenance['archives'])
    old=dict(np.load('btc_core_forecast/long_results/july_arrays.npz',allow_pickle=False))
    extra={k:[] for k in old}
    for i in range(int(old['idx'][-1])+1,len(a)-72*12):
        if t[i]%3600000:continue
        x,s=f.feature(a,i,t[i]);extra['x'].append(np.r_[x,regime(a,i)])
        for k,value in [('idx',i),('anchors',t[i]),('spot',a[i,4]),('scales',s)]:extra[k].append(value)
        extra['close'].append(np.log(a[i+np.arange(1,73)*12,4]/a[i,4])/s)
        extra['high'].append([np.log(a[i+(h-1)*12+1:i+h*12+1,2].max()/a[i,4])/s for h in range(1,73)])
        extra['low'].append([np.log(a[i+(h-1)*12+1:i+h*12+1,3].min()/a[i,4])/s for h in range(1,73)])
    d={k:np.concatenate([v,np.asarray(extra[k])]) for k,v in old.items()}
    calstart=anchor-60*86400000;ends=d['anchors']+72*3600000
    tr=np.flatnonzero((d['anchors']>=calstart-365*86400000)&(ends<calstart))
    ca=np.flatnonzero((d['anchors']>=calstart)&(ends<anchor))
    if len(tr)<1000 or len(ca)<240:raise ValueError('insufficient training/calibration')
    model=c.fit(d['x'],d['close'],d['high'],d['low'],tr,ca)
    cc=ca[np.linspace(0,len(ca)-1,min(w.MAX_SCENARIOS,len(ca)),dtype=int)]
    hx=har_features(d['x'],d['scales']);y=c.volatility_targets(d['close']);heads=[]
    for k in range(4):
        head=make_pipeline(StandardScaler(),Ridge(alpha=1.));head.fit(hx[tr],y[tr,k]);heads.append(head)
    ema=ewma_from_raw('inputs/deployment_archives/assembled.json.gz',d['idx'])
    model['har_heads']=heads;model['har_calibration_logs']=np.column_stack([h.predict(hx[cc]) for h in heads])
    model['calibration_ratios']={'vol24':np.ones(len(cc)),'vol1':d['x'][cc,5]/d['scales'][cc],
        'vol4':d['x'][cc,9]/d['scales'][cc],**{k:v[cc]/d['scales'][cc] for k,v in ema.items()}}
    model['trading_authority']=False
    out.mkdir(exist_ok=True,parents=True)
    dump(model,out/'distribution.joblib',compress=3)
    manifest={'schema':'btc-current-frozen-distribution-component-v1','trading_authority':False,
        'full_system_ready':False,'prospective_skill_proven':False,'scope':'conditional spot uncertainty component, not directional/core entry model',
        'model_sha256':hashlib.sha256((out/'distribution.joblib').read_bytes()).hexdigest(),
        'training_input_sha256':rawsha,'training_input_end_utc':f.iso(anchor),
        'training_n':len(tr),'calibration_n':len(ca),'scenario_n':len(cc),
        'last_training_label_end':f.iso(ends[tr].max()),'last_calibration_label_end':f.iso(ends[ca].max()),
        'archives':archives,'R6_numeric_used':False,'macro_numeric_used':False,
        'history_used_in_development':True,'actual_OTC_execution_tested':False}
    f.write(out/'manifest.json',manifest)
    print('RUNTIME_MODEL_FROZEN',manifest['training_n'],manifest['calibration_n'],(out/'distribution.joblib').stat().st_size,flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',default='btc_core_forecast/runtime')
    main(parser.parse_args().output)
