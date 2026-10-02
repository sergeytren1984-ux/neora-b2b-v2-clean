from pathlib import Path
exec(Path(__file__).with_name('evaluate_regime.py').read_text().split("print('samples'")[0])
for h in ('1h','4h','24h'):
 y=np.array(labels[h]);old=np.array(heuristic[h]);prior=np.bincount(y[train],minlength=3)/sum(train);pp=np.tile(prior,(sum(hold),1)); yy=np.eye(3)[y[hold]]
 print(h,'train_prior',prior.round(3),'hold_prior',(np.bincount(y[hold],minlength=3)/sum(hold)).round(3),'climatology_brier',round(np.mean(np.sum((pp-yy)**2,axis=1)),4),'climatology_logloss',round(log_loss(y[hold],pp,labels=[0,1,2]),4))
