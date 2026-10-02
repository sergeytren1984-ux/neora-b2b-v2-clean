from pathlib import Path
exec(Path(__file__).with_name('evaluate_regime.py').read_text().split("print('samples'")[0])
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score
for h in ('1h','4h','24h'):
 y=np.array(labels[h]);old=np.array(heuristic[h]);
 for depth in (2,3):
  m=HistGradientBoostingClassifier(max_iter=100,max_depth=depth,learning_rate=0.04,l2_regularization=10.0,min_samples_leaf=100,random_state=42).fit(X[train],y[train])
  pred=m.predict_proba(X)
  for mask,label in [(valid,'valid'),(hold,'hold')]:
   pp=pred[mask];one=np.eye(3)[y[mask]]
   print(h,depth,label,'brier',round(np.mean(np.sum((pp-one)**2,axis=1)),4),'logloss',round(log_loss(y[mask],pp,labels=[0,1,2]),4),'AUCup',round(roc_auc_score(y[mask]==2,pp[:,2]),3),flush=True)
