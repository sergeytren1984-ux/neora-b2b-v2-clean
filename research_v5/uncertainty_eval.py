from pathlib import Path
exec(Path(__file__).with_name('evaluate_regime.py').read_text().split("print('samples'")[0])
rng=np.random.default_rng(42)
for h in ('1h','4h','24h'):
 y=np.array(labels[h]);old=np.array(heuristic[h]);sc=StandardScaler().fit(X[train]);m=LogisticRegression(C=0.03,max_iter=500).fit(sc.transform(X[train]),y[train]);pred=m.predict_proba(sc.transform(X));prior=np.bincount(y[train],minlength=3)/sum(train);idx=np.where(hold)[0];one=np.eye(3)[y[idx]]
 d_old=np.sum((old[idx]-one)**2,axis=1)-np.sum((pred[idx]-one)**2,axis=1)
 d_prior=np.sum((np.tile(prior,(len(idx),1))-one)**2,axis=1)-np.sum((pred[idx]-one)**2,axis=1)
 # Resample calendar-week blocks to retain overlapping 24h outcomes and clustering.
 week=np.array([str(x)[:10] for x in dates[idx]])
 import datetime as dt
 blocks=np.array([dt.date.fromisoformat(x).toordinal()//7 for x in week]);uniq=np.unique(blocks)
 draw=[]
 for diff in (d_old,d_prior):
  means=[]
  for _ in range(1000):
   chosen=rng.choice(uniq,size=len(uniq),replace=True)
   sampled=np.concatenate([np.flatnonzero(blocks==b) for b in chosen])
   means.append(np.mean(diff[sampled]))
  draw.append((round(float(np.mean(diff)),4),[round(float(z),4) for z in np.percentile(means,[2.5,97.5])]))
 print(h,'v4 minus ridge',draw[0],'prior minus ridge',draw[1])
