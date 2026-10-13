"""Conditional joint path distribution; fixed historical diagnostic, never trade-ready.

Predicts uncertainty rather than adding another unvalidated drift coefficient.
All trajectory transformations preserve hourly extrema and path dependence.
Calibration and training outcomes finish before the scored period.
"""
import argparse, pathlib
import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
import forecast as f
import walkforward as w

KNOTS = np.array([1, 4, 24, 72])

def volatility_targets(close):
    increments = np.diff(np.column_stack([np.zeros(len(close)), close]), axis=1)
    return np.column_stack([np.log(np.maximum(np.sqrt(np.mean(increments[:, :h]**2, axis=1)), 1e-6)) for h in KNOTS])

def interpolate(log_scales):
    return np.exp(np.column_stack([np.interp(np.arange(1,73), KNOTS, row) for row in log_scales]).T)

def transform(close, high, low, multiplier):
    prev = np.column_stack([np.zeros(len(close)), close[:, :-1]])
    updated = np.cumsum((close-prev)*multiplier, axis=1)
    newprev = np.column_stack([np.zeros(len(close)), updated[:, :-1]])
    upper = np.maximum(newprev + (high-prev)*multiplier, np.maximum(updated,newprev))
    lower = np.minimum(newprev + (low-prev)*multiplier, np.minimum(updated,newprev))
    if not all(np.isfinite(a).all() for a in (updated, upper, lower)):
        raise ValueError('nonfinite transformed trajectory')
    if np.any(upper+1e-10<np.maximum(updated,newprev)) or np.any(lower-1e-10>np.minimum(updated,newprev)):
        raise ValueError('incoherent transformed extrema')
    return updated, upper, lower

def fit(x, close, high, low, tr, ca):
    y = volatility_targets(close)
    heads=[]
    for k in range(4):
        head=HistGradientBoostingRegressor(loss='squared_error', learning_rate=.035,
            max_iter=100, max_leaf_nodes=7, min_samples_leaf=150,
            l2_regularization=10, random_state=60113)
        head.fit(x[tr],y[tr,k]); heads.append(head)
    choose=np.linspace(0,len(ca)-1,min(w.MAX_SCENARIOS,len(ca)),dtype=int)
    cc=ca[choose]
    calibration_logs=np.column_stack([h.predict(x[cc]) for h in heads])
    model={'heads':heads,'calibration_logs':calibration_logs,
           'close':close[cc],'high':high[cc],'low':low[cc]}
    return model

def distribution(model,x,sigma,logs=None):
    if logs is None:logs=np.array([head.predict(x[None])[0] for head in model['heads']])
    if not np.isfinite(logs).all():raise ValueError('invalid volatility prediction')
    # Fixed bounded ratio guards numeric instability, never fills missing factors.
    multiplier=interpolate(np.clip(logs-model['calibration_logs'],np.log(.05),np.log(20)))
    c,h,l=transform(model['close'],model['high'],model['low'],multiplier)
    return c*sigma,h*sigma,l*sigma

def run(arrays,out):
    a=dict(np.load(arrays,allow_pickle=False));out=pathlib.Path(out);out.mkdir(exist_ok=True,parents=True)
    report={'schema':'btc-conditional-joint-path-diagnostic-v1',
        'historical_only':True,'history_already_used':True,'trading_authority':False,
        'prospective_skill_proven':False,'macro_and_R6_numeric_inputs':False,'folds':{}}
    for start,end in w.FOLDS:
        tr,ca,te=w.split(a['anchors'],start,end)
        m=fit(a['x'],a['close'],a['high'],a['low'],tr,ca)
        predictions=np.column_stack([head.predict(a['x'][te]) for head in m['heads']])
        rows={h:[] for h in w.HORIZONS};touch=[];econ={h:[] for h in w.HORIZONS};always={h:[] for h in w.HORIZONS};signals={h:0 for h in w.HORIZONS}
        for row_index,j in enumerate(te):
            c,h,l=distribution(m,a['x'][j],a['scales'][j],predictions[row_index]);spot=a['spot'][j]
            base=m['close']*a['scales'][j];bh=m['high']*a['scales'][j];bl=m['low']*a['scales'][j]
            actual=a['close'][j]*a['scales'][j]
            true=f.first_passage(a['high'][j:j+1]*a['scales'][j],a['low'][j:j+1]*a['scales'][j])[0]
            pp=np.bincount(f.first_passage(h,l),minlength=4)/len(c)
            bp=np.bincount(f.first_passage(bh,bl),minlength=4)/len(c)
            touch.append(np.sum((bp-np.eye(4)[true])**2)-np.sum((pp-np.eye(4)[true])**2))
            for hours in w.HORIZONS:
                samples=spot*np.exp(c[:,hours-1]);bs=spot*np.exp(base[:,hours-1]);truth=spot*np.exp(actual[hours-1])
                q=np.quantile(samples,[.1,.5,.9]);yy=np.eye(3)[w.endpoint_classes(actual[None],hours)[0]]
                p=np.bincount(w.endpoint_classes(c,hours),minlength=3)/len(c)
                b=np.bincount(w.endpoint_classes(base,hours),minlength=3)/len(c)
                rows[hours].append([abs(spot-truth)-abs(q[1]-truth),f.crps(bs,truth)-f.crps(samples,truth),
                    float(q[0]<=truth<=q[2]),np.sum((b-yy)**2)-np.sum((p-yy)**2),
                    q[2]-q[0]+10*max(q[0]-truth,0)+10*max(truth-q[2],0)])
                predicted=147600/(spot*np.exp(c[:,hours])+350)-147600/(spot*np.exp(c[:,0])+350)
                waiting=predicted.mean()>0 and np.mean(predicted>0)>.60
                realized=147600/(spot*np.exp(actual[hours])+350)-147600/(spot*np.exp(actual[0])+350)
                signals[hours]+=int(waiting);econ[hours].append(realized if waiting else 0.);always[hours].append(realized)
        result={'price':{},'wait':{},'barrier_brier_gain':f.daily_stats(np.array(touch),a['anchors'][te])}
        for hours in w.HORIZONS:
            rr=np.array(rows[hours]);aa=a['anchors'][te]
            result['price'][str(hours)]={'mae_gain':f.daily_stats(rr[:,0],aa),
                'crps_gain':f.daily_stats(rr[:,1],aa),'coverage_80pct':float(rr[:,2].mean()),
                'direction_brier_gain':f.daily_stats(rr[:,3],aa),'interval_score':float(rr[:,4].mean())}
            gain=np.array(econ[hours]);result['wait'][str(hours)]={'signals':signals[hours],
                'vs_buy_now':f.daily_stats(gain,aa),'vs_always_wait':f.daily_stats(gain-np.array(always[hours]),aa)}
        report['folds'][start[:10]]=result;f.write(out/'diagnostic.json',report)
        print('CONDITIONAL_PATH_FOLD',start[:10],{h:round(v['crps_gain']['среднее_улучшение'],3) for h,v in result['price'].items()},flush=True)
    report['all_folds_crps_positive']=all(v['crps_gain']['среднее_улучшение']>0 for fold in report['folds'].values() for v in fold['price'].values())
    report['all_folds_wait_vs_both_positive']=all(v['vs_buy_now']['среднее_улучшение']>0 and v['vs_always_wait']['среднее_улучшение']>0 for fold in report['folds'].values() for v in fold['wait'].values())
    f.write(out/'diagnostic.json',report)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--arrays',required=True);p.add_argument('--output',required=True)
    args=p.parse_args();run(args.arrays,args.output)
