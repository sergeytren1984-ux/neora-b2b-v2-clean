"""Frozen benchmark research. The protocol was committed before this script ran."""
from __future__ import annotations
import gzip, hashlib, json, math
from pathlib import Path
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

HERE=Path(__file__).resolve().parent
protocol=json.loads((HERE/'first_passage_protocol_20261003.json').read_text())
source=HERE/'data/btc_1h_2024_to_sep24_2026.json.gz'
source_sha=hashlib.sha256(source.read_bytes()).hexdigest()
raw=json.loads(gzip.decompress(source.read_bytes()))
t=np.array([int(x[0]) for x in raw],dtype=np.int64)
open_=np.array([float(x[1]) for x in raw]);high=np.array([float(x[2]) for x in raw]);low=np.array([float(x[3]) for x in raw]);close=np.array([float(x[4]) for x in raw]);vol=np.array([float(x[5]) for x in raw])
valid_candle=np.array([int(x[6])==int(x[0])+3599999 and l<=min(o,c)<=max(o,c)<=h and v>=0
                       for x,o,h,l,c,v in zip(raw,open_,high,low,close,vol)])
gap=np.concatenate(([False],np.diff(t)!=3600000))
invalid=(~valid_candle)|gap
prefix=np.concatenate(([0],np.cumsum(invalid.astype(int))))
records=[]
for i in range(168,len(raw)-168):
    if prefix[i+1]-prefix[i-168]:continue
    p=close[i]
    if not math.isfinite(p) or p<=0:continue
    ret=lambda h:math.log(p/close[i-h])
    lr=np.diff(np.log(close[i-72:i+1]))
    feat=[ret(4),ret(24),ret(72),float(np.mean(abs(lr[-24:]))),float(np.mean(abs(lr))),
          math.log(max(1e-8,float(np.mean(vol[i-24:i])))/max(1e-8,float(np.mean(vol[i-168:i]))))]
    if all(map(math.isfinite,feat)):records.append((i,feat))
ix=np.array([x[0] for x in records],dtype=int);X=np.array([x[1] for x in records])
dates=np.array([str(np.datetime64(int(t[i]+3600000),'ms')) for i in ix])
train=dates<'2026-01-01T00:00:00.000';valid=(dates>='2026-01-02T00:00:00.000')&(dates<'2026-07-01T00:00:00.000');diagnostic=(dates>='2026-07-02T00:00:00.000')&(dates<'2026-09-25T00:00:00.000')
classes=protocol['classes'];out={'schema':'btc-first-passage-two-horizons-result-v1',
    'protocol_sha256':hashlib.sha256((HERE/'first_passage_protocol_20261003.json').read_bytes()).hexdigest(),
    'history_gzip_sha256':source_sha,'candidate_is_probability':False,'trading_authority':False,'scenarios':{}}
rng=np.random.default_rng(20261003)
for scenario in protocol['scenarios']:
    h=scenario['horizon_hours'];lower_ratio=scenario['lower_usdt']/protocol['reference_snapshot']['price_usdt'];upper_ratio=scenario['upper_usdt']/protocol['reference_snapshot']['price_usdt']
    labels=[];eligible=[]
    for j,i in enumerate(ix):
        if i+h>=len(raw) or prefix[i+h+1]-prefix[i+1]:continue
        lo=p=close[i]*lower_ratio;hi=close[i]*upper_ratio
        outcome=2
        for k in range(i+1,i+h+1):
            dn=low[k]<=lo;up=high[k]>=hi
            if dn and up:outcome=3;break
            if dn:outcome=0;break
            if up:outcome=1;break
        labels.append(outcome);eligible.append(j)
    subset=np.array(eligible,dtype=int);y=np.array(labels,dtype=int);xx=X[subset]
    masks={'validation_H1_2026':valid[subset],'inspected_Jul_Sep_2026':diagnostic[subset]}
    scaler=StandardScaler().fit(xx[train[subset]])
    model=LogisticRegression(C=.03,max_iter=500).fit(scaler.transform(xx[train[subset]]),y[train[subset]])
    candidate=np.zeros((len(y),4));candidate[:,model.classes_]=model.predict_proba(scaler.transform(xx))
    frequencies=np.bincount(y[train[subset]],minlength=4).astype(float);frequencies/=frequencies.sum()
    baseline=np.tile(frequencies,(len(y),1))
    scenario_result={'train_n':int(sum(train[subset])),'training_frequency':dict(zip(classes,frequencies.tolist())),
                     'coefficient_features':['return_4h','return_24h','return_72h','mean_abs_return_24h','mean_abs_return_72h','log_volume_24h_vs_168h'],
                     'evaluation':{}}
    for name,mask in masks.items():
        yy=y[mask];one=np.eye(4)[yy];cand=candidate[mask];base=baseline[mask]
        def metrics(pp):return {'brier':float(np.mean(np.sum((pp-one)**2,axis=1))),
                                 'log_loss':float(np.mean(-np.log(np.maximum(pp[np.arange(len(yy)),yy],1e-9))))}
        dates_block=np.array([d[:10] for d in dates[subset][mask]])
        week=np.array([str(np.datetime64(d,'D').astype('datetime64[W]')) for d in dates_block])
        blocks=[np.where(week==w)[0] for w in np.unique(week)]
        paired=np.sum((base-one)**2,axis=1)-np.sum((cand-one)**2,axis=1)
        boots=[]
        for _ in range(1000):
            selected=np.concatenate([blocks[k] for k in rng.integers(0,len(blocks),len(blocks))])
            boots.append(float(np.mean(paired[selected])))
        scenario_result['evaluation'][name]={'n':len(yy),'counts':dict(zip(classes,np.bincount(yy,minlength=4).tolist())),
              'baseline':metrics(base),'simple_logistic':metrics(cand),
              'brier_gain_baseline_minus_logistic':float(np.mean(paired)),
              'weekly_block_bootstrap_brier_gain_95ci':np.quantile(boots,[.025,.975]).tolist()}
    out['scenarios'][scenario['id']]=scenario_result
print(json.dumps(out,sort_keys=True,indent=2))
