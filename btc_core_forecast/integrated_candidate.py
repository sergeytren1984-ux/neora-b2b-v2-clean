"""The single fixed R6/macro candidate; never fit a spot-only substitute."""
import numpy as np,datetime as dt
from factor_integration import FEATURE_NAMES
import supervised_direction as direction

CANDIDATE='R6_MACRO_SIGN_PATH_V1'

def fit_verified(a,rows,train,calibration):
    if a['x'].shape!=(len(rows),len(FEATURE_NAMES)):raise ValueError('integrated feature matrix mismatch')
    for i,row in enumerate(rows):
        if not row.get('eligible_for_research_matrix'):raise ValueError('required factor row unavailable')
        if tuple(row['feature_names'])!=FEATURE_NAMES or not np.allclose(a['x'][i],row['features'],rtol=1e-12,atol=1e-12):raise ValueError('factor matrix differs from verified row')
        if (row.get('macro_quotes') or {}).get('immutable_collector_source_proven') is not True:raise ValueError('macro collector source unpinned')
    for name in ('close','high','low'):
        if a[name].shape!=(len(rows),72) or not np.isfinite(a[name]).all():raise ValueError('complete observed 72h target trajectories required')
    train,calibration=np.asarray(train),np.asarray(calibration)
    if min(len(train),len(calibration))==0:raise ValueError('separate causal training and calibration sets required')
    if np.intersect1d(train,calibration).size:raise ValueError('training/calibration overlap')
    if a['anchors'][np.r_[train,calibration]].max()+72*3600000>int(dt.datetime.now(dt.timezone.utc).timestamp()*1000):raise ValueError('training targets have not closed yet')
    if a['anchors'][train].max()+72*3600000>=a['anchors'][calibration].min():raise ValueError('training targets overlap calibration')
    for h in (1,4,24):
        if len(np.unique(a['close'][train,h-1]>0))!=2:raise ValueError('both direction classes required')
    model=direction.fit(a,train,calibration)
    model.update(candidate_id=CANDIDATE,integrated_feature_names=FEATURE_NAMES,
        paired_causal_factor_training_verified=True,full_system_ready=False,prospective_skill_proven=False)
    return model

def paths(model,x,sigma):
    if model.get('candidate_id')!=CANDIDATE:raise ValueError('not the fixed integrated candidate')
    if tuple(model.get('integrated_feature_names',()))!=FEATURE_NAMES:raise ValueError('wrong fitted input schema')
    return direction.paths(model,np.asarray(x),sigma)
