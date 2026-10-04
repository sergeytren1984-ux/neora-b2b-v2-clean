"""Core utilities for BTC predictive vNext research.

Research-only. No trading authority. All features are computed from candles closed
at or before the anchor. Adaptive baselines use only outcomes whose due time is
strictly earlier than the current prediction anchor.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

CLASSES = ("LOWER_FIRST", "UPPER_FIRST", "NEITHER", "AMBIGUOUS_SAME_BAR")
SEED = 20261004


def read_klines(path: str | Path, duration_ms: int):
    path = Path(path)
    blob = path.read_bytes()
    if path.suffix == ".gz":
        import gzip
        source_bytes = gzip.decompress(blob)
        rows = json.loads(source_bytes)
    else:
        source_bytes = blob
        rows = json.loads(blob)
    t = np.asarray([int(r[0]) for r in rows], dtype=np.int64)
    o = np.asarray([float(r[1]) for r in rows])
    hi = np.asarray([float(r[2]) for r in rows])
    lo = np.asarray([float(r[3]) for r in rows])
    c = np.asarray([float(r[4]) for r in rows])
    v = np.asarray([float(r[5]) for r in rows])
    trades = np.asarray([float(r[8]) for r in rows])
    taker = np.asarray([float(r[9]) for r in rows])
    if len(t) < 500 or np.any(np.diff(t) != duration_ms):
        raise ValueError(f"gaps or duplicate timestamps in {path}")
    if any(int(r[6]) != int(r[0]) + duration_ms - 1 for r in rows):
        raise ValueError(f"partial candle in {path}")
    if not np.all((lo <= np.minimum(o, c)) & (hi >= np.maximum(o, c)) & (v >= 0)):
        raise ValueError(f"OHLC/volume invariant failed in {path}")
    # Hash logical source bytes, not the gzip container header whose mtime changes on rebuild.
    return t, o, hi, lo, c, v, trades, taker, hashlib.sha256(source_bytes).hexdigest()


def _efficiency(c, i, window):
    x = c[i-window:i+1]
    path = np.sum(np.abs(np.diff(x)))
    return 0.0 if path <= 0 else float((x[-1] - x[0]) / path)


def _atr(hi, lo, c, i, window=14):
    start = i-window+1
    prev = c[start-1:i]
    tr = np.maximum(hi[start:i+1]-lo[start:i+1],
                    np.maximum(np.abs(hi[start:i+1]-prev),
                               np.abs(lo[start:i+1]-prev)))
    return float(np.mean(tr))


def build_hourly_features(t, hi, lo, c, v, trades, taker, max_horizon=168):
    start = 169
    ix = np.arange(start, len(t)-max_horizon, dtype=np.int64)
    z = np.log(c)
    names = [
        "ret_1h","ret_4h","ret_12h","ret_24h","ret_72h","ret_168h",
        "mean_abs_4h","mean_abs_12h","mean_abs_24h","mean_abs_72h",
        "std_4h","std_12h","std_24h","std_72h",
        "range_24h","range_72h","vol_ratio_24_168",
        "volume_ratio_4_24","volume_ratio_24_168",
        "trades_ratio_4_24","trades_ratio_24_168",
        "taker_ratio_1h","taker_ratio_4h","taker_ratio_24h","taker_accel_4h",
        "efficiency_6h","efficiency_12h","efficiency_24h",
        "dist_prev24_high","dist_prev24_low","ret_accel_4_vs_24",
        "atr14_pct"
    ]
    X = np.zeros((len(ix), len(names)), dtype=float)
    regimes = np.zeros(len(ix), dtype=np.int8)
    vol_measure = np.zeros(len(ix), dtype=float)
    atr_abs = np.zeros(len(ix), dtype=float)
    for row, i in enumerate(ix):
        r = np.diff(z[i-168:i+1])
        mean_abs = {w: float(np.mean(np.abs(r[-w:]))) for w in (4,12,24,72)}
        std = {w: float(np.std(r[-w:])) for w in (4,12,24,72)}
        ret = {w: float(z[i]-z[i-w]) for w in (1,4,12,24,72,168)}
        prev24h = np.max(hi[i-24:i])
        prev24l = np.min(lo[i-24:i])
        atr = _atr(hi, lo, c, i, 14)
        atr_abs[row] = atr
        vol_measure[row] = std[24]
        tratio1 = taker[i] / max(v[i], 1e-12)
        tratio4 = np.sum(taker[i-3:i+1]) / max(np.sum(v[i-3:i+1]), 1e-12)
        tratio24 = np.sum(taker[i-23:i+1]) / max(np.sum(v[i-23:i+1]), 1e-12)
        prev4 = np.sum(taker[i-7:i-3]) / max(np.sum(v[i-7:i-3]), 1e-12)
        vals = [
            ret[1],ret[4],ret[12],ret[24],ret[72],ret[168],
            mean_abs[4],mean_abs[12],mean_abs[24],mean_abs[72],
            std[4],std[12],std[24],std[72],
            (np.max(hi[i-23:i+1])-np.min(lo[i-23:i+1]))/c[i],
            (np.max(hi[i-71:i+1])-np.min(lo[i-71:i+1]))/c[i],
            mean_abs[24]/max(float(np.mean(np.abs(r))),1e-12),
            math.log((np.mean(v[i-3:i+1])+1e-12)/(np.mean(v[i-23:i+1])+1e-12)),
            math.log((np.mean(v[i-23:i+1])+1e-12)/(np.mean(v[i-167:i+1])+1e-12)),
            math.log((np.mean(trades[i-3:i+1])+1)/(np.mean(trades[i-23:i+1])+1)),
            math.log((np.mean(trades[i-23:i+1])+1)/(np.mean(trades[i-167:i+1])+1)),
            tratio1,tratio4,tratio24,tratio4-prev4,
            _efficiency(c,i,6),_efficiency(c,i,12),_efficiency(c,i,24),
            (c[i]-prev24h)/c[i],(c[i]-prev24l)/c[i],
            ret[4]-ret[24]/6.0, atr/c[i]
        ]
        X[row] = vals
        # Pre-anchor deterministic gate: compression, trend, breakout/post-breakout, reversal.
        if mean_abs[24] < 0.75 * max(float(np.mean(np.abs(r))), 1e-12):
            regimes[row] = 0  # LOW_VOL_COMPRESSION
        elif (c[i] > prev24h) or (c[i] < prev24l):
            regimes[row] = 2  # BREAKOUT_POST_BREAKOUT
        elif np.sign(ret[4]) != np.sign(ret[24]) and abs(ret[4]) > 2.0*max(mean_abs[24],1e-12):
            regimes[row] = 3  # REVERSAL_LIQUIDATION
        else:
            regimes[row] = 1  # TREND/OTHER
    dates = t[ix].astype("datetime64[ms]") + np.timedelta64(1, "h")
    if not np.all(np.isfinite(X)):
        raise ValueError("non-finite hourly features")
    return ix, dates, X, names, regimes, vol_measure, atr_abs


def build_15m_features(t, hi, lo, c, v, trades, taker, max_forward_bars=16):
    start = 384
    ix = np.arange(start, len(t)-max_forward_bars, dtype=np.int64)
    z = np.log(c)
    names = [
        "ret_15m","ret_1h","ret_4h","ret_12h","ret_24h","ret_96h",
        "mean_abs_1h","mean_abs_4h","mean_abs_12h","mean_abs_24h",
        "std_1h","std_4h","std_12h","std_24h",
        "range_4h","range_24h","vol_ratio_4h_24h",
        "volume_ratio_1h_4h","volume_ratio_4h_24h",
        "trades_ratio_1h_4h","trades_ratio_4h_24h",
        "taker_ratio_15m","taker_ratio_1h","taker_ratio_4h","taker_accel_1h",
        "efficiency_1h","efficiency_4h","dist_prev4h_high","dist_prev4h_low"
    ]
    X = np.zeros((len(ix),len(names)),dtype=float)
    regimes = np.zeros(len(ix),dtype=np.int8)
    vol_measure = np.zeros(len(ix),dtype=float)
    for row,i in enumerate(ix):
        r=np.diff(z[i-384:i+1])
        ret={k:float(z[i]-z[i-k]) for k in (1,4,16,48,96,384)}
        ma={k:float(np.mean(np.abs(r[-k:]))) for k in (4,16,48,96)}
        sd={k:float(np.std(r[-k:])) for k in (4,16,48,96)}
        prevh=np.max(hi[i-16:i]);prevl=np.min(lo[i-16:i])
        tr15=taker[i]/max(v[i],1e-12)
        tr1=np.sum(taker[i-3:i+1])/max(np.sum(v[i-3:i+1]),1e-12)
        tr4=np.sum(taker[i-15:i+1])/max(np.sum(v[i-15:i+1]),1e-12)
        prev1=np.sum(taker[i-7:i-3])/max(np.sum(v[i-7:i-3]),1e-12)
        X[row]=[
            ret[1],ret[4],ret[16],ret[48],ret[96],ret[384],
            ma[4],ma[16],ma[48],ma[96],sd[4],sd[16],sd[48],sd[96],
            (np.max(hi[i-15:i+1])-np.min(lo[i-15:i+1]))/c[i],
            (np.max(hi[i-95:i+1])-np.min(lo[i-95:i+1]))/c[i],
            ma[16]/max(ma[96],1e-12),
            math.log((np.mean(v[i-3:i+1])+1e-12)/(np.mean(v[i-15:i+1])+1e-12)),
            math.log((np.mean(v[i-15:i+1])+1e-12)/(np.mean(v[i-95:i+1])+1e-12)),
            math.log((np.mean(trades[i-3:i+1])+1)/(np.mean(trades[i-15:i+1])+1)),
            math.log((np.mean(trades[i-15:i+1])+1)/(np.mean(trades[i-95:i+1])+1)),
            tr15,tr1,tr4,tr1-prev1,_efficiency(c,i,4),_efficiency(c,i,16),
            (c[i]-prevh)/c[i],(c[i]-prevl)/c[i]
        ]
        vol_measure[row]=sd[16]
        if ma[16] < .75*max(ma[96],1e-12):
            regimes[row]=0
        elif c[i]>prevh or c[i]<prevl:
            regimes[row]=2
        elif np.sign(ret[4])!=np.sign(ret[16]) and abs(ret[4])>2*max(ma[16],1e-12):
            regimes[row]=3
        else:
            regimes[row]=1
    dates=t[ix].astype("datetime64[ms]")+np.timedelta64(15,"m")
    if not np.all(np.isfinite(X)):
        raise ValueError("non-finite 15m features")
    return ix,dates,X,names,regimes,vol_measure


def first_touch_variable(ix, hi, lo, c, lower, upper, horizon_steps):
    lower=np.asarray(lower,dtype=float);upper=np.asarray(upper,dtype=float)
    if lower.ndim==0: lower=np.full(len(ix),float(lower))
    if upper.ndim==0: upper=np.full(len(ix),float(upper))
    y=np.full(len(ix),2,dtype=np.int8)
    when=np.full(len(ix),horizon_steps+1,dtype=np.int16)
    for step in range(1,horizon_steps+1):
        active=when>horizon_steps
        dn=lo[ix+step]<=lower
        up=hi[ix+step]>=upper
        hit=active&(dn|up)
        y[hit]=np.where(dn[hit]&up[hit],3,np.where(dn[hit],0,1))
        when[hit]=step
    return y,when


def target_percent(ix,c,hi,lo,lower_ratio,upper_ratio,horizon_steps):
    return first_touch_variable(ix,hi,lo,c,c[ix]*lower_ratio,c[ix]*upper_ratio,horizon_steps)


def target_distance(ix,c,hi,lo,distance,horizon_steps):
    d=np.asarray(distance,dtype=float)
    return first_touch_variable(ix,hi,lo,c,c[ix]-d,c[ix]+d,horizon_steps)


def masks(dates, due_delta, train_end, cal_start, cal_end, test_start, test_end):
    train_end=np.datetime64(train_end);cal_start=np.datetime64(cal_start)
    cal_end=np.datetime64(cal_end);test_start=np.datetime64(test_start);test_end=np.datetime64(test_end)
    due=dates+due_delta
    return (due<train_end,
            (dates>=cal_start)&(due<cal_end),
            (dates>=test_start)&(dates<test_end))


def full_proba(model,X):
    p=np.zeros((len(X),4),dtype=float)
    p[:,model.classes_.astype(int)]=model.predict_proba(X)
    return p


def calibrate(cal_p,test_p,y_cal):
    if len(np.unique(y_cal))<2:
        return test_p
    trans=lambda p:np.log(np.clip(p,1e-8,1))
    m=LogisticRegression(C=.05,max_iter=400)
    m.fit(trans(cal_p),y_cal)
    return full_proba(m,trans(test_p))


def _fit_hazard(X,y,when,train,horizon_steps,step):
    risk_x=[];risk_y=[]
    tr=np.flatnonzero(train)
    for elapsed in range(step,horizon_steps+1,step):
        at=tr[when[tr]>elapsed-step]
        if len(at)==0: continue
        risk_x.append(np.column_stack((X[at],np.full(len(at),elapsed/horizon_steps))))
        risk_y.append(np.where(when[at]<=elapsed,y[at],2))
    if not risk_x:
        raise ValueError("empty hazard training set")
    yy=np.concatenate(risk_y)
    model=make_pipeline(StandardScaler(),LogisticRegression(C=.025,max_iter=350))
    model.fit(np.concatenate(risk_x),yy)
    return model


def _hazard_cumulative(model,X,horizon_steps,step):
    out=np.zeros((len(X),4),dtype=float);survive=np.ones(len(X),dtype=float)
    for elapsed in range(step,horizon_steps+1,step):
        h=full_proba(model,np.column_stack((X,np.full(len(X),elapsed/horizon_steps))))
        out[:,0]+=survive*h[:,0];out[:,1]+=survive*h[:,1];out[:,3]+=survive*h[:,3]
        survive*=h[:,2]
    out[:,2]=survive
    s=out.sum(axis=1,keepdims=True)
    return out/np.maximum(s,1e-12)


def fit_candidates(X,regime,y,when,train,cal,test,horizon_steps,hazard_step):
    yy=y[train]
    freq=(np.bincount(yy,minlength=4)+.5)/(len(yy)+2.0)
    preds={"frequency_train":np.tile(freq,(int(np.sum(test)),1))}
    logistic=make_pipeline(StandardScaler(),LogisticRegression(C=.03,max_iter=450))
    logistic.fit(X[train],yy)
    preds["logistic"]=calibrate(full_proba(logistic,X[cal]),full_proba(logistic,X[test]),y[cal])
    tree=HistGradientBoostingClassifier(max_iter=110,max_leaf_nodes=15,min_samples_leaf=80,
                                        learning_rate=.04,l2_regularization=12,random_state=SEED)
    tree.fit(X[train],yy)
    preds["gbdt"]=calibrate(full_proba(tree,X[cal]),full_proba(tree,X[test]),y[cal])
    global_h=_fit_hazard(X,y,when,train,horizon_steps,hazard_step)
    cal_idx=np.flatnonzero(cal);test_idx=np.flatnonzero(test)
    gh_cal=_hazard_cumulative(global_h,X[cal_idx],horizon_steps,hazard_step)
    gh_test=_hazard_cumulative(global_h,X[test_idx],horizon_steps,hazard_step)
    preds["competing_risks"]=calibrate(gh_cal,gh_test,y[cal])
    # Regime-dependent competing risks: each pre-anchor regime gets its own hazard head.
    reg_cal=gh_cal.copy();reg_test=gh_test.copy()
    for r in range(4):
        trr=train&(regime==r)
        if np.sum(trr)<250 or len(np.unique(y[trr]))<2:
            continue
        try:
            head=_fit_hazard(X,y,when,trr,horizon_steps,hazard_step)
        except Exception:
            continue
        cm=regime[cal_idx]==r;tm=regime[test_idx]==r
        if np.any(cm): reg_cal[cm]=_hazard_cumulative(head,X[cal_idx[cm]],horizon_steps,hazard_step)
        if np.any(tm): reg_test[tm]=_hazard_cumulative(head,X[test_idx[tm]],horizon_steps,hazard_step)
    preds["regime_competing_risks"]=calibrate(reg_cal,reg_test,y[cal])
    return preds


def adaptive_baselines(dates,y,regime,vol_measure,train_mask,test_mask,due_delta):
    dates=np.asarray(dates);due=dates+due_delta
    train_counts=np.bincount(y[train_mask],minlength=4)+.5
    fixed=train_counts/train_counts.sum()
    q=np.quantile(vol_measure[train_mask],[1/3,2/3])
    vol_bin=np.digitize(vol_measure,q,right=True)
    test_idx=np.flatnonzero(test_mask)
    names=("rolling30d","rolling60d","rolling90d","ewma30d","regime90d","vol90d")
    out={n:np.zeros((len(test_idx),4),dtype=float) for n in names}
    for pos,i in enumerate(test_idx):
        t=dates[i]
        end=np.searchsorted(due,t,side="left")
        def slice_idx(days):
            start=np.searchsorted(dates,t-np.timedelta64(days,"D"),side="left")
            return np.arange(start,end,dtype=int)
        for days,name in ((30,"rolling30d"),(60,"rolling60d"),(90,"rolling90d")):
            ids=slice_idx(days)
            cnt=np.bincount(y[ids],minlength=4)+.5 if len(ids) else train_counts.copy()
            out[name][pos]=cnt/cnt.sum()
        ids=slice_idx(180)
        if len(ids):
            age=np.asarray((t-dates[ids])/np.timedelta64(1,"D"),dtype=float)
            w=np.exp(-math.log(2)*age/30.0)
            cnt=np.bincount(y[ids],weights=w,minlength=4)+.5
            out["ewma30d"][pos]=cnt/cnt.sum()
        else:
            out["ewma30d"][pos]=fixed
        ids=slice_idx(90);same=ids[regime[ids]==regime[i]]
        cnt=np.bincount(y[same],minlength=4)+.5 if len(same)>=30 else train_counts.copy()
        out["regime90d"][pos]=cnt/cnt.sum()
        samev=ids[vol_bin[ids]==vol_bin[i]]
        cnt=np.bincount(y[samev],minlength=4)+.5 if len(samev)>=30 else train_counts.copy()
        out["vol90d"][pos]=cnt/cnt.sum()
    return out


def metrics(p,y):
    one=np.eye(4)[y];eps=1e-12
    ans={"brier":float(np.mean(np.sum((p-one)**2,axis=1))),
         "log_loss":float(-np.mean(np.log(np.clip(p[np.arange(len(y)),y],eps,1))))}
    conf=p.max(axis=1);correct=(p.argmax(axis=1)==y)
    ece=0.0
    for a,b in zip(np.linspace(0,1,11)[:-1],np.linspace(0,1,11)[1:]):
        m=(conf>=a)&(conf<(b if b<1 else 1.000001))
        if np.any(m): ece+=np.mean(m)*abs(np.mean(correct[m])-np.mean(conf[m]))
    ans["ece10"]=float(ece)
    for k,name in ((0,"lower"),(1,"upper")):
        actual=(y==k).astype(int)
        ans[name+"_pr_auc"]=float(average_precision_score(actual,p[:,k])) if np.sum(actual) else None
        ans[name+"_roc_auc"]=float(roc_auc_score(actual,p[:,k])) if len(np.unique(actual))==2 else None
    return ans


def block_ci(reference,p,y,dates,n_boot=400):
    one=np.eye(4)[y]
    diff=np.sum((reference-one)**2,axis=1)-np.sum((p-one)**2,axis=1)
    weeks=dates.astype("datetime64[W]")
    blocks=[np.flatnonzero(weeks==w) for w in np.unique(weeks)]
    rng=np.random.default_rng(SEED)
    boot=[]
    for _ in range(n_boot):
        ids=np.concatenate([blocks[j] for j in rng.integers(len(blocks),size=len(blocks))])
        boot.append(float(np.mean(diff[ids])))
    return [float(x) for x in np.quantile(boot,[.025,.975])]


def evaluate_fold(X,regime,vol_measure,dates,y,when,train,cal,test,due_delta,
                  horizon_steps,hazard_step):
    base=adaptive_baselines(dates,y,regime,vol_measure,train,test,due_delta)
    pred=fit_candidates(X,regime,y,when,train,cal,test,horizon_steps,hazard_step)
    pred.update(base)
    yt=y[test];dt=dates[test]
    score={k:metrics(v,yt) for k,v in pred.items()}
    baseline_names=["frequency_train","rolling30d","rolling60d","rolling90d","ewma30d","regime90d","vol90d"]
    strongest=min(baseline_names,key=lambda n:score[n]["brier"])
    for name,p in pred.items():
        score[name]["brier_gain_vs_strongest_baseline_ci"]=block_ci(pred[strongest],p,yt,dt)
    return {"n":int(np.sum(test)),"counts":np.bincount(yt,minlength=4).tolist(),
            "strongest_baseline":strongest,"models":score}


def shift_report(X,names,dates,regime,y,period_a,period_b):
    a=(dates>=np.datetime64(period_a[0]))&(dates<np.datetime64(period_a[1]))
    b=(dates>=np.datetime64(period_b[0]))&(dates<np.datetime64(period_b[1]))
    rows=[]
    for j,name in enumerate(names):
        ma=float(np.mean(X[a,j]));mb=float(np.mean(X[b,j]))
        sa=float(np.std(X[a,j]));sb=float(np.std(X[b,j]))
        pooled=math.sqrt((sa*sa+sb*sb)/2.0)+1e-12
        rows.append({"feature":name,"mean_a":ma,"mean_b":mb,"smd_b_minus_a":(mb-ma)/pooled})
    rows.sort(key=lambda r:abs(r["smd_b_minus_a"]),reverse=True)
    return {
        "period_a":{"range":period_a,"n":int(np.sum(a)),
                    "class_frequency":(np.bincount(y[a],minlength=4)/max(np.sum(a),1)).tolist(),
                    "regime_frequency":(np.bincount(regime[a],minlength=4)/max(np.sum(a),1)).tolist()},
        "period_b":{"range":period_b,"n":int(np.sum(b)),
                    "class_frequency":(np.bincount(y[b],minlength=4)/max(np.sum(b),1)).tolist(),
                    "regime_frequency":(np.bincount(regime[b],minlength=4)/max(np.sum(b),1)).tolist()},
        "top_feature_shifts":rows[:15]
    }
