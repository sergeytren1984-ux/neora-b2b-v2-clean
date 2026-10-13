"""Fixed replacement candidate: learn signed direction, preserve joint paths.

Regularization and weighting are fixed before this diagnostic. Calibration
outcomes finish before each scored fold. Previously inspected history cannot
establish independent predictive or trading effectiveness.
"""
import argparse
import numpy as np
from scipy.optimize import minimize_scalar
from scipy.special import expit
from sklearn.linear_model import LogisticRegression
import conditional_path as cp
import joint_candidate as joint

SPEC={'schema':'btc-supervised-sign-path-candidate-v1','features':'30 causal spot/regime features',
    'direction_horizons_hours':[1,4,24],'classifier':'logistic regression',
    'regularization_C':.1,'calibration':'held-out additive log-odds correction bounded [-3,3]',
    'path_weight':'geometric mean of three sign likelihood ratios',
    'ratio_bounds':[.05,20],'hypothetical_entry_policy':'expected extra BTC > 0',
    'previous_candidate_rejected':True,'historical_selection_bias':True,
    'R6_numeric_used':False,'macro_numeric_used':False,'actual_OTC_used':False,
    'trading_authority':False,'full_system_ready':False}

def fit(a,tr,ca):
    vm=cp.fit(a['x'],a['close'],a['high'],a['low'],tr,ca)
    mu=a['x'][tr].mean(0);sd=np.maximum(a['x'][tr].std(0),1e-8)
    train=np.clip((a['x'][tr]-mu)/sd,-6,6);cal=np.clip((a['x'][ca]-mu)/sd,-6,6)
    heads=[];offsets=[]
    for h in (1,4,24):
        y=(a['close'][:,h-1]>0).astype(int)
        if len(np.unique(y[tr]))!=2:raise ValueError('both signed directions required in training')
        head=LogisticRegression(C=.1,max_iter=500,solver='lbfgs',random_state=60113).fit(train,y[tr])
        logits=head.decision_function(cal)
        def loss(offset):return float(np.mean(np.logaddexp(0,logits+offset)-y[ca]*(logits+offset)))
        correction=minimize_scalar(loss,bounds=(-3,3),method='bounded')
        if not correction.success:raise ValueError('direction calibration failed')
        heads.append(head);offsets.append(float(correction.x))
    return {'volatility':vm,'mu':mu,'sd':sd,'direction_heads':heads,'calibration_offsets':offsets,
        'trading_authority':False,'prospective_skill_proven':False}

def tilt(close,probabilities):
    p=np.asarray(probabilities,dtype=float)
    if p.shape!=(3,) or not np.isfinite(p).all() or np.any((p<=0)|(p>=1)):raise ValueError('invalid signed direction probabilities')
    if close.ndim!=2 or close.shape[1]!=72 or not np.isfinite(close).all():raise ValueError('invalid path support')
    logweight=np.zeros(len(close));unsupported=[]
    for k,h in enumerate((1,4,24)):
        positive=close[:,h-1]>0;prior=float(positive.mean())
        if prior in (0.,1.):unsupported.append(h);continue
        ratio=np.where(positive,p[k]/prior,(1-p[k])/(1-prior))
        logweight+=np.log(np.clip(ratio,.05,20))/3
    weight=np.exp(logweight-logweight.max());weight/=weight.sum()
    return weight,unsupported

def paths(model,x,sigma,logs=None):
    if not np.isfinite(x).all() or not np.isfinite(sigma) or sigma<=0:raise ValueError('invalid causal input')
    c,h,l=cp.distribution(model['volatility'],x,sigma,logs)
    xx=np.clip((x-model['mu'])/model['sd'],-6,6)[None]
    p=np.array([expit(head.decision_function(xx)[0]+offset) for head,offset in zip(model['direction_heads'],model['calibration_offsets'])])
    weights,_=tilt(c,np.clip(p,1e-8,1-1e-8))
    return c,h,l,weights

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--arrays',required=True);p.add_argument('--output',required=True)
    args=p.parse_args();joint.run(args.arrays,args.output,'expected-btc',fit,paths,SPEC)
