"""Live feature extraction matching predictive_vnext4/core.py exactly.

Only data at or before the closed anchor candle are read. Parity is tested against
historical research feature matrices before prospective launch.
"""
from __future__ import annotations

import math
import numpy as np

from predictive_vnext4.core import _efficiency, _atr


HOURLY_NAMES = [
    "ret_1h","ret_4h","ret_12h","ret_24h","ret_72h","ret_168h",
    "mean_abs_4h","mean_abs_12h","mean_abs_24h","mean_abs_72h",
    "std_4h","std_12h","std_24h","std_72h",
    "range_24h","range_72h","vol_ratio_24_168",
    "volume_ratio_4_24","volume_ratio_24_168",
    "trades_ratio_4_24","trades_ratio_24_168",
    "taker_ratio_1h","taker_ratio_4h","taker_ratio_24h","taker_accel_4h",
    "efficiency_6h","efficiency_12h","efficiency_24h",
    "dist_prev24_high","dist_prev24_low","ret_accel_4_vs_24",
    "atr14_pct"
]

EARLY15M_NAMES = [
    "ret_15m","ret_1h","ret_4h","ret_12h","ret_24h","ret_96h",
    "mean_abs_1h","mean_abs_4h","mean_abs_12h","mean_abs_24h",
    "std_1h","std_4h","std_12h","std_24h",
    "range_4h","range_24h","vol_ratio_4h_24h",
    "volume_ratio_1h_4h","volume_ratio_4h_24h",
    "trades_ratio_1h_4h","trades_ratio_4h_24h",
    "taker_ratio_15m","taker_ratio_1h","taker_ratio_4h","taker_accel_1h",
    "efficiency_1h","efficiency_4h","dist_prev4h_high","dist_prev4h_low"
]


def hourly_feature(hi,lo,c,v,trades,taker,i=None):
    i=len(c)-1 if i is None else int(i)
    if i<169:
        raise ValueError("need at least 170 closed hourly candles")
    z=np.log(c)
    r=np.diff(z[i-168:i+1])
    mean_abs={w:float(np.mean(np.abs(r[-w:]))) for w in (4,12,24,72)}
    std={w:float(np.std(r[-w:])) for w in (4,12,24,72)}
    ret={w:float(z[i]-z[i-w]) for w in (1,4,12,24,72,168)}
    prev24h=np.max(hi[i-24:i]);prev24l=np.min(lo[i-24:i])
    atr=_atr(hi,lo,c,i,14)
    tratio1=taker[i]/max(v[i],1e-12)
    tratio4=np.sum(taker[i-3:i+1])/max(np.sum(v[i-3:i+1]),1e-12)
    tratio24=np.sum(taker[i-23:i+1])/max(np.sum(v[i-23:i+1]),1e-12)
    prev4=np.sum(taker[i-7:i-3])/max(np.sum(v[i-7:i-3]),1e-12)
    values=[
        ret[1],ret[4],ret[12],ret[24],ret[72],ret[168],
        mean_abs[4],mean_abs[12],mean_abs[24],mean_abs[72],
        std[4],std[12],std[24],std[72],
        (np.max(hi[i-23:i+1])-np.min(lo[i-23:i+1]))/c[i],
        (np.max(hi[i-71:i+1])-np.min(lo[i-71:i+1]))/c[i],
        mean_abs[24]/max(float(np.mean(np.abs(r))),1e-12),
        math.log((np.mean(v[i-3:i+1])+1e-12)/(np.mean(v[i-23:i+1])+1e-12)),
        math.log((np.mean(v[i-23:i+1])+1e-12)/(np.mean(v[i-167:i+1])+1e-12)),
        math.log((np.mean(trades[i-3:i+1])+1)/(np.mean(trades[i-23:i+1])+1)),
        math.log((np.mean(trades[i-23:i+1])+1)/(np.mean(trades[i-167:i+1])+1)),
        tratio1,tratio4,tratio24,tratio4-prev4,
        _efficiency(c,i,6),_efficiency(c,i,12),_efficiency(c,i,24),
        (c[i]-prev24h)/c[i],(c[i]-prev24l)/c[i],
        ret[4]-ret[24]/6.0,atr/c[i]
    ]
    X=np.asarray(values,dtype=float)
    if not np.all(np.isfinite(X)): raise ValueError("non-finite hourly live feature")
    return X, {"reference_price":float(c[i]),"rv24":std[24],"atr14_abs":atr}


def early15m_feature(hi,lo,c,v,trades,taker,i=None):
    i=len(c)-1 if i is None else int(i)
    if i<384:
        raise ValueError("need at least 385 closed 15m candles")
    z=np.log(c)
    r=np.diff(z[i-384:i+1])
    ret={k:float(z[i]-z[i-k]) for k in (1,4,16,48,96,384)}
    ma={k:float(np.mean(np.abs(r[-k:]))) for k in (4,16,48,96)}
    sd={k:float(np.std(r[-k:])) for k in (4,16,48,96)}
    prevh=np.max(hi[i-16:i]);prevl=np.min(lo[i-16:i])
    tr15=taker[i]/max(v[i],1e-12)
    tr1=np.sum(taker[i-3:i+1])/max(np.sum(v[i-3:i+1]),1e-12)
    tr4=np.sum(taker[i-15:i+1])/max(np.sum(v[i-15:i+1]),1e-12)
    prev1=np.sum(taker[i-7:i-3])/max(np.sum(v[i-7:i-3]),1e-12)
    values=[
        ret[1],ret[4],ret[16],ret[48],ret[96],ret[384],
        ma[4],ma[16],ma[48],ma[96],sd[4],sd[16],sd[48],sd[96],
        (np.max(hi[i-15:i+1])-np.min(lo[i-15:i+1]))/c[i],
        (np.max(hi[i-95:i+1])-np.min(lo[i-95:i+1]))/c[i],
        ma[16]/max(ma[96],1e-12),
        math.log((np.mean(v[i-3:i+1])+1e-12)/(np.mean(v[i-15:i+1])+1e-12)),
        math.log((np.mean(v[i-15:i+1])+1e-12)/(np.mean(v[i-95:i+1])+1e-12)),
        math.log((np.mean(trades[i-3:i+1])+1)/(np.mean(trades[i-15:i+1])+1)),
        math.log((np.mean(trades[i-15:i+1])+1)/(np.mean(trades[i-95:i+1])+1)),
        tr15,tr1,tr4,tr1-prev1,_efficiency(c,i,4),_efficiency(c,i,16),
        (c[i]-prevh)/c[i],(c[i]-prevl)/c[i]
    ]
    X=np.asarray(values,dtype=float)
    if not np.all(np.isfinite(X)): raise ValueError("non-finite 15m live feature")
    return X, {"reference_price":float(c[i]),"rv4h":sd[16]}
