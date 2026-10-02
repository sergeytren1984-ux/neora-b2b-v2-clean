from pathlib import Path
exec(Path(__file__).with_name('evaluate_regime.py').read_text().split("print('samples'")[0])
# dates/features correspond to raw index 168 onward; skip any gap records (none in this source).
from sklearn.metrics import log_loss
cs=np.array([[float(x[2]),float(x[3]),float(x[4])] for x in raw])
by_time={datetime.fromtimestamp((x[0]+3600000)/1000,timezone.utc).isoformat():i for i,x in enumerate(raw)}
labels=[]
for j,feat in enumerate(X):
 i=by_time[dates[j]];ref=cs[i,2];delta=ref*feat[keys.index('atr24_pct')]/100
 lo,hi=ref-delta,ref+delta
 hit=2
 for row in cs[i+1:i+25]:
  lower=row[1]<=lo; upper=row[0]>=hi
  if lower and upper: hit=3;break
  if lower:hit=0;break
  if upper:hit=1;break
 labels.append(hit)
y=np.array(labels)
sc=StandardScaler().fit(X[train]);z=sc.transform(X)
m=LogisticRegression(C=0.03,max_iter=500).fit(z[train],y[train])
pred=m.predict_proba(z)
prior=np.bincount(y[train],minlength=4)/sum(train)
for mask,name in [(valid,'valid'),(hold,'hold')]:
 one=np.eye(4)[y[mask]]; base=np.tile(prior,(sum(mask),1))
 for tag,pp in [('ridge',pred[mask]),('prior',base)]:
  print(name,tag,'brier',round(np.mean(np.sum((pp-one)**2,axis=1)),4),'logloss',round(log_loss(y[mask],pp,labels=[0,1,2,3]),4))
 print(name,'freq',np.bincount(y[mask],minlength=4)/sum(mask))
