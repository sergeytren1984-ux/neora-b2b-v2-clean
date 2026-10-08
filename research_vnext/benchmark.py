"""Research-only, as-of first-passage benchmark. No production forecast is emitted.

Usage: python research_vnext/benchmark.py --history btc_1h_2024_to_sep24_2026.json --out research_vnext/result.json
The predeclared split and hyperparameters below must not be tuned on the evaluation block.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

CLASSES = ("LOWER_FIRST", "UPPER_FIRST", "NEITHER", "AMBIGUOUS_SAME_BAR")
SEED = 20261004
# Hourly source cannot answer the mandatory 5m/15m ablation. These targets are
# evaluated only as a preliminary spot-only benchmark, never as an admission test.
TARGETS = [(p, h) for p in (.0075, .01, .015, .02) for h in (4, 12, 24, 72, 168)]
ATR_TARGETS = [(a, h) for a in (1., 1.5, 2.) for h in (4, 12, 24, 72, 168)]
TRAIN_END = np.datetime64("2025-10-01T00:00:00")
CAL_START = np.datetime64("2025-10-01T00:00:00")
CAL_END = np.datetime64("2026-01-01T00:00:00")
TEST_START = np.datetime64("2026-01-08T00:00:00")
TEST_END = np.datetime64("2026-07-01T00:00:00")


def read_history(path):
    import gzip
    blob = Path(path).read_bytes()
    rows = json.loads(gzip.decompress(blob) if str(path).endswith(".gz") else blob)
    t = np.array([int(r[0]) for r in rows], dtype=np.int64)
    o, hi, lo, c, v, trades, taker = (np.array([float(r[j]) for r in rows]) for j in (1, 2, 3, 4, 5, 8, 9))
    valid = (np.diff(t) == 3600000).all() and all(int(r[6]) == int(r[0]) + 3599999 for r in rows)
    if not valid or not np.all((lo <= np.minimum(o, c)) & (np.maximum(o, c) <= hi) & (v >= 0)):
        raise ValueError("Gap, partial candle or inconsistent OHLC: source rejected")
    return t, hi, lo, c, v, trades, taker, hashlib.sha256(blob).hexdigest()


def features(t, hi, lo, c, v, trades, taker, maximum=168):
    ix = np.arange(169, len(t) - maximum, 4)  # common 4h anchors for all candidates
    z = np.log(c)
    x = []
    regimes = []
    for i in ix:
        r = np.diff(z[i-168:i+1])
        vol_recent = np.mean(np.abs(r[-24:]))
        vol_long = np.mean(np.abs(r))
        ret4 = z[i] - z[i-4]
        ret24 = z[i] - z[i-24]
        width = (np.max(hi[i-24:i+1]) - np.min(lo[i-24:i+1])) / c[i]
        baseline = [z[i]-z[i-k] for k in (1, 4, 12, 24, 72, 168)]
        baseline += [vol_recent, vol_long, width,
                     np.log((np.mean(v[i-24:i+1])+1e-12)/(np.mean(v[i-168:i+1])+1e-12))]
        micro = [np.mean(taker[i-3:i+1]/np.maximum(v[i-3:i+1],1e-12)),
                 np.mean(taker[i-23:i+1]/np.maximum(v[i-23:i+1],1e-12)),
                 np.log((np.mean(trades[i-3:i+1])+1)/(np.mean(trades[i-23:i+1])+1)),
                 np.log((np.mean(v[i-3:i+1])+1)/(np.mean(v[i-23:i+1])+1)),
                 (c[i]-np.max(hi[i-24:i]))/c[i],
                 (c[i]-np.min(lo[i-24:i]))/c[i]]
        x.append((baseline, micro))
        # Deterministic, prior-candle gate; this is not the production regime-v5.
        regimes.append(0 if vol_recent < .8*vol_long else
                       2 if c[i] >= np.max(hi[i-24:i]) or c[i] <= np.min(lo[i-24:i]) else
                       3 if np.sign(ret4) != np.sign(ret24) and abs(ret4) > 2*vol_recent else 1)
    base = np.asarray([q[0] for q in x]); micro = np.asarray([q[1] for q in x])
    if not np.all(np.isfinite(base)) or not np.all(np.isfinite(micro)):
        raise ValueError("Nonfinite features")
    dates = t[ix].astype("datetime64[ms]") + np.timedelta64(1, "h")
    return ix, dates, base, micro, np.asarray(regimes)


def first_touch(ix, hi, lo, c, percentage, horizon, distance=None):
    y = np.full(len(ix), 2, dtype=np.int8)
    when = np.full(len(ix), horizon + 1, dtype=np.int16)
    lower = c[ix] * (1-percentage) if distance is None else c[ix]-distance
    upper = c[ix] * (1+percentage) if distance is None else c[ix]+distance
    for step in range(1, horizon+1):
        active = when > horizon
        down = lo[ix+step] <= lower
        up = hi[ix+step] >= upper
        touched = active & (down | up)
        y[touched] = np.where(down[touched] & up[touched], 3,
                              np.where(down[touched], 0, 1))
        when[touched] = step
    return y, when


def masks(dates, horizon, train_end=TRAIN_END, cal_start=CAL_START,
          cal_end=CAL_END, test_start=TEST_START, test_end=TEST_END):
    # Training labels must be due strictly before calibration starts; calibration
    # labels strictly before test starts. No dependent horizon crosses a boundary.
    due = dates + np.timedelta64(horizon, "h")
    return (due < train_end, (dates >= cal_start) & (due < cal_end),
            (dates >= test_start) & (dates < test_end))


def full_proba(model, X):
    p = np.zeros((len(X), 4), dtype=float)
    p[:, model.classes_] = model.predict_proba(X)
    return p


def fit_candidates(X, gate, y, train, cal, test, when, horizon):
    yy = y[train]
    freq = (np.bincount(yy, minlength=4) + .5) / (len(yy) + 2)
    predictions = {"frequency": np.tile(freq, (sum(test), 1))}
    base = make_pipeline(StandardScaler(), LogisticRegression(C=.03, max_iter=350))
    base.fit(X[train], yy)
    predictions["logistic"] = calibrate(full_proba(base, X[cal]), full_proba(base, X[test]), y[cal])
    tree = HistGradientBoostingClassifier(max_iter=80, max_leaf_nodes=12, min_samples_leaf=100,
                                           learning_rate=.045, l2_regularization=10, random_state=SEED)
    tree.fit(X[train], yy)
    predictions["gbdt"] = calibrate(full_proba(tree, X[cal]), full_proba(tree, X[test]), y[cal])

    # Multinomial per-interval hazards. Every training row is at risk until the
    # observed first event. Same-hour touches are explicitly the fourth class.
    step = 1 if horizon <= 24 else 4 if horizon <= 72 else 12
    risk_x = []; risk_y = []
    tr = np.flatnonzero(train)
    for elapsed in range(step, horizon+1, step):
        at_risk = tr[when[tr] > elapsed-step]
        if not len(at_risk): continue
        risk_x.append(np.column_stack((X[at_risk], np.full(len(at_risk), elapsed/horizon))))
        risk_y.append(np.where(when[at_risk] <= elapsed, y[at_risk], 2))
    hazard = make_pipeline(StandardScaler(), LogisticRegression(C=.025, max_iter=250))
    hazard.fit(np.concatenate(risk_x), np.concatenate(risk_y))
    def cumulative(indices):
        xx = X[indices]
        out = np.zeros((len(indices),4)); survive = np.ones(len(indices))
        for elapsed in range(step,horizon+1,step):
            h = full_proba(hazard, np.column_stack((xx,np.full(len(xx),elapsed/horizon))))
            out[:,0] += survive*h[:,0]; out[:,1] += survive*h[:,1]; out[:,3] += survive*h[:,3]
            survive *= h[:,2]
        out[:,2] = survive
        return out
    predictions["competing_risks"] = calibrate(cumulative(np.flatnonzero(cal)),
                                                  cumulative(np.flatnonzero(test)), y[cal])
    gated_cal = full_proba(base,X[cal]); gated_test = full_proba(base,X[test])
    cal_idx, test_idx = np.flatnonzero(cal), np.flatnonzero(test)
    for regime in range(4):
        group = train & (gate == regime)
        if sum(group) < 100 or len(np.unique(y[group])) < 2: continue
        head = make_pipeline(StandardScaler(), LogisticRegression(C=.03,max_iter=350))
        head.fit(X[group], y[group])
        cm = gate[cal_idx] == regime; tm = gate[test_idx] == regime
        gated_cal[cm] = full_proba(head,X[cal_idx[cm]])
        gated_test[tm] = full_proba(head,X[test_idx[tm]])
    predictions["regime_gated"] = calibrate(gated_cal,gated_test,y[cal])
    return predictions


def calibrate(cal_p, test_p, y_cal):
    # Independent temporal calibration block. Log probability stacking is
    # regularized and cannot train on the out-of-time score block.
    transform = lambda p: np.log(np.clip(p, 1e-7, 1))
    model = LogisticRegression(C=.05,max_iter=350)
    model.fit(transform(cal_p),y_cal)
    return full_proba(model,transform(test_p))


def metrics(p,y):
    eps=1e-12; one=np.eye(4)[y]
    ans={"brier":float(np.mean(np.sum((p-one)**2,axis=1))),
         "log_loss":float(-np.mean(np.log(np.clip(p[np.arange(len(y)),y],eps,1))))}
    for k,name in ((0,"lower"),(1,"upper")):
        binary=(y==k).astype(int)
        ans[name+"_pr_auc"] = float(average_precision_score(binary,p[:,k])) if sum(binary) else None
        ans[name+"_roc_auc"] = float(roc_auc_score(binary,p[:,k])) if len(np.unique(binary))==2 else None
    ans["calibration_10bin_ece"] = float(sum(np.sum((p.max(axis=1)>=a)&(p.max(axis=1)<b))*abs(
        np.mean((p.argmax(axis=1)==y)[(p.max(axis=1)>=a)&(p.max(axis=1)<b)])-
        np.mean(p.max(axis=1)[(p.max(axis=1)>=a)&(p.max(axis=1)<b)]))
        for a,b in zip(np.linspace(0,1,11)[:-1],np.linspace(0,1,11)[1:])
        if np.any((p.max(axis=1)>=a)&(p.max(axis=1)<b)))/len(y))
    return ans


def block_ci(reference,p,y,dates,seed=SEED):
    one=np.eye(4)[y]
    diff=np.sum((reference-one)**2,axis=1)-np.sum((p-one)**2,axis=1)
    weeks=dates.astype("datetime64[W]")
    blocks=[np.flatnonzero(weeks==w) for w in np.unique(weeks)]
    rng=np.random.default_rng(seed)
    boot=[np.mean(diff[np.concatenate([blocks[j] for j in rng.integers(len(blocks),size=len(blocks))])]) for _ in range(1000)]
    return [float(x) for x in np.quantile(boot,[.025,.975])]


def run(path):
    t,hi,lo,c,v,trades,taker,digest=read_history(path)
    ix,dates,spot,micro,gate=features(t,hi,lo,c,v,trades,taker)
    output={"schema":"btc-predictive-research-vnext-preliminary", "history_sha256":digest,
            "data_resolution":"closed_1h_only", "forecast_authority":False,"predictive_accept":False,
            "reason":"Mandatory 5m/15m and 2024-25 derivatives unavailable; H1 2026 already examined, no untouched prospective test",
            "split":{"train_label_due_before":str(TRAIN_END),"calibration":str(CAL_START)+" to "+str(CAL_END),
                     "test":str(TEST_START)+" to "+str(TEST_END),"anchor_stride_hours":4},
            "target_counts":{},"comparisons":{},"walk_forward":{}}
    for pct,h in TARGETS:
        y,when=first_touch(ix,hi,lo,c,pct,h)
        train,cal,test=masks(dates,h)
        key=f"pm{pct*100:g}pct_{h}h"
        output["target_counts"][key]={"train":np.bincount(y[train],minlength=4).tolist(),
                                         "cal":np.bincount(y[cal],minlength=4).tolist(),
                                         "test":np.bincount(y[test],minlength=4).tolist()}
    # ATR14 is measured only from the 14 most recent CLOSED hourly candles.
    atr=np.asarray([np.mean(np.maximum(hi[i-13:i+1]-lo[i-13:i+1],
        np.maximum(abs(hi[i-13:i+1]-c[i-14:i]),abs(lo[i-13:i+1]-c[i-14:i])))) for i in ix])
    for multiple,h in ATR_TARGETS:
        y,_=first_touch(ix,hi,lo,c,0,h,distance=multiple*atr)
        train,cal,test=masks(dates,h)
        output["target_counts"][f"pm{multiple:g}atr14_1h_{h}h"]={
            "train":np.bincount(y[train],minlength=4).tolist(),
            "cal":np.bincount(y[cal],minlength=4).tolist(),
            "test":np.bincount(y[test],minlength=4).tolist()}
    # Fixed representative target. Choose once, without examining target scores.
    pct,h=.01,24
    y,when=first_touch(ix,hi,lo,c,pct,h)
    train,cal,test=masks(dates,h)
    for name,X in (("spot_only",spot),("spot_plus_hourly_flow",np.column_stack((spot,micro)))):
        candidates=fit_candidates(X,gate,y,train,cal,test,when,h)
        result={}
        for model,p in candidates.items():
            result[model]={"scores":metrics(p,y[test]),
                           "weekly_block_brier_gain_vs_frequency_95ci":block_ci(candidates["frequency"],p,y[test],dates[test]),
                           "weekly_block_brier_gain_vs_logistic_95ci":block_ci(candidates["logistic"],p,y[test],dates[test]),
                           "quarterly_brier":[metrics(p[q],y[test][q])["brier"] for q in
                              ((dates[test]<np.datetime64('2026-04-01')),
                               (dates[test]>=np.datetime64('2026-04-01')))]}
        output["comparisons"][name]=result
    for model in output["comparisons"]["spot_only"]:
        a=output["comparisons"]["spot_only"][model]["scores"]
        b=output["comparisons"]["spot_plus_hourly_flow"][model]["scores"]
        output.setdefault("hourly_flow_ablation",{})[model]={
            "brier_gain":a["brier"]-b["brier"],"log_loss_gain":a["log_loss"]-b["log_loss"],
            "lower_pr_auc_gain":b["lower_pr_auc"]-a["lower_pr_auc"],
            "upper_pr_auc_gain":b["upper_pr_auc"]-a["upper_pr_auc"]}
    folds=(
        ("2025Q3", "2025-04-01", "2025-04-01", "2025-07-01", "2025-07-08", "2025-10-01"),
        ("2025Q4", "2025-07-01", "2025-07-01", "2025-10-01", "2025-10-08", "2026-01-01"),
        ("2026H1", "2025-10-01", "2025-10-01", "2026-01-01", "2026-01-08", "2026-07-01"))
    for label,*boundaries in folds:
        tr,ca,te=masks(dates,h,*map(np.datetime64,boundaries))
        preds=fit_candidates(np.column_stack((spot,micro)),gate,y,tr,ca,te,when,h)
        output["walk_forward"][label]={"n":int(sum(te)),"models":{}}
        for model,p in preds.items():
            baseline=preds["frequency"]
            output["walk_forward"][label]["models"][model]={"scores":metrics(p,y[te]),
                "brier_gain_vs_frequency_ci":block_ci(baseline,p,y[te],dates[te])}
    output["decision"]={"best_observed":"gbdt spot_plus_hourly_flow on 2026H1",
        "predictive_accept":False,
        "reasons":["H1 2026 is previously inspected, not untouched",
                   "Must beat strongest baseline in Brier and Log Loss with strictly positive lower CI",
                   "5m/15m, external families and 2024-25 derivatives are unavailable"]}
    return output


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--history",required=True);parser.add_argument("--out",required=True)
    args=parser.parse_args();out=run(args.history)
    Path(args.out).write_text(json.dumps(out,indent=2,ensure_ascii=False,sort_keys=True)+"\n")
    print(json.dumps({"out":args.out,"sha256":hashlib.sha256(Path(args.out).read_bytes()).hexdigest()},indent=2))
