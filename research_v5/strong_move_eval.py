from pathlib import Path
exec(Path(__file__).with_name('evaluate_regime.py').read_text().split("print('samples'")[0])
from sklearn.metrics import roc_auc_score,average_precision_score
by_time={c['close_time']:i for i,c in enumerate(cs)}
for h,threshold in ((4,1.0),(24,2.0)):
 y=np.array([100*(cs[by_time[d]+h]['close']/cs[by_time[d]]['close']-1)>threshold for d in dates],dtype=int)
 sc=StandardScaler().fit(X[train]);z=sc.transform(X);m=LogisticRegression(C=0.03,max_iter=500).fit(z[train],y[train]);pred=m.predict_proba(z)[:,1]
 for mask,name in ((valid,'valid'),(hold,'hold')):
  print(h,threshold,name,'N',sum(y[mask]),'base',round(y[mask].mean(),3),'auc',round(roc_auc_score(y[mask],pred[mask]),3),'ap',round(average_precision_score(y[mask],pred[mask]),3))
