"""Frozen, spot-only 4h upside-tail warning, no fitted dependency at runtime."""
import math
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from regime_v4.model import candle_features

def candidate(candles, artifact):
    f=candle_features(candles)
    names=artifact['features']
    z=[(float(f[n])-m)/s for n,m,s in zip(names,artifact['standard_mean'],artifact['standard_scale'])]
    score=float(artifact['intercept'])+sum(a*b for a,b in zip(artifact['coefficients'],z))
    p=1/(1+math.exp(-max(-40,min(40,score))))
    if not math.isfinite(p): raise ValueError('nonfinite tail score')
    return p,f

def warn(closed,artifact):
    if len(closed)<889: raise ValueError('need 889 consecutive closed hours')
    scores=[]
    for end in range(len(closed)-721,len(closed)-1):
        p,_=candidate(closed[end-168:end+1],artifact)
        scores.append(p)
    current,features=candidate(closed[-169:],artifact)
    rank=sum(x<=current for x in scores)/len(scores)
    return {'tail_event':'BTCUSDT spot close at anchor+4h > anchor close by 1%',
            'candidate_estimate':round(current,6),
            'candidate_status':'HISTORICALLY_VALIDATED_PROSPECTIVE_UNPROVEN',
            'rank_30d':round(rank,6),'alert':rank>=0.8,
            'cutoff_rank':0.8,'past_scores_count':len(scores),
            'atr24_pct':features['atr24_pct'],
            'regime_features':{k:features[k] for k in
                ('technical','structure','flow','breakout','persistence','change_point','trend_quality')},
            'feature_sources':['closed_binance_spot_1h'],
            'excluded_from_numeric_model':['open_interest','funding','dxy','nasdaq_futures','us10y','etf_flows','macro']}
