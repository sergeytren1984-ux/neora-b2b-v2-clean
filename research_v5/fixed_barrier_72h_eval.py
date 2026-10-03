"""Diagnostic fixed relative barrier-first comparison; no probability publication."""
from pathlib import Path
import os
os.chdir(Path(__file__).resolve().parents[1])
exec(Path('research_v5/evaluate_regime.py').read_text().split("print('samples'")[0])
from sklearn.metrics import log_loss

reference=84586.0
lower=82500.0/reference
upper=87500.0/reference
by_time={c['close_time']:i for i,c in enumerate(cs)}
truth=[];usable=[]
for n,when in enumerate(dates):
    i=by_time[when]
    if i+72>=len(cs):continue
    lo=cs[i]['close']*lower;hi=cs[i]['close']*upper
    label=2
    for candle in cs[i+1:i+73]:
        down=candle['low']<=lo;up=candle['high']>=hi
        if down and up:label=3;break
        if down:label=0;break
        if up:label=1;break
    usable.append(n);truth.append(label)
ix=np.array(usable);y=np.array(truth)
ambiguous=int(sum(y==3))
keep=y!=3;ix=ix[keep];y=y[keep]
sc=StandardScaler().fit(X[ix][train[ix]])
z=sc.transform(X[ix]);m=LogisticRegression(C=.03,max_iter=500).fit(z[train[ix]],y[train[ix]])
p=m.predict_proba(z)
prior=np.bincount(y[train[ix]],minlength=3)/sum(train[ix])
for mask,name in ((valid[ix],'H1_2026_validation'),(hold[ix],'Jul_Sep_diagnostic')):
    yy=y[mask];one=np.eye(3)[yy];base=np.tile(prior,(sum(mask),1))
    for label,prob in (('ridge',p[mask]),('training_prior',base)):
        print(name,label,'n',len(yy),'brier',round(float(np.mean(np.sum((prob-one)**2,axis=1))),5),
              'logloss',round(float(log_loss(yy,prob,labels=[0,1,2])),5),flush=True)
    print(name,'actual_frequencies',np.bincount(yy,minlength=3)/len(yy),
          'same_candle_ambiguous_excluded_total',ambiguous,flush=True)
