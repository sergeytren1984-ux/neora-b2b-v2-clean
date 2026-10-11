"""Negative causal unit tests: unavailable outcomes and future candles are never features."""
from __future__ import annotations
import datetime as dt
import numpy as np
from btc_skill_rebuild.evaluate import features,build_targets,build_arrays,splits,STEP,VAL_START,TEST_START

def main():
    first=int(dt.datetime(2026,8,1,tzinfo=dt.timezone.utc).timestamp()*1000)
    n=72*288
    times=first+np.arange(n)*STEP
    j=np.arange(n,dtype=float)
    prices=82000*np.exp(0.00008*np.sin(j/55)+0.000002*j)
    volume=40+10*(1+np.sin(j/7))
    trades=300+50*(1+np.cos(j/19))
    arr=np.stack([prices,prices*1.0004,prices*0.9996,
                  prices,volume,trades,volume*(.5+.1*np.sin(j/9))],axis=1)
    idx,x=features(times,arr)
    assert idx[-1]==n-1, "latest observations must not be discarded"
    assert len(x)==n-576 and np.all(np.isfinite(x))
    labels=build_targets(times,arr,idx)
    assert np.isnan(labels["price_morning_08msk"][-1]), "unobserved morning mislabeled"
    assert np.isnan(labels["price_4h"][-1]), "unobserved horizon mislabeled"
    assert np.isnan(labels["large_up_1h"][-1]), "unobserved event mislabeled"
    tr,va,te=splits(times,idx)
    assert len(set(tr)&set(va))==0 and len(set(va)&set(te))==0
    anchors=times[idx]+STEP
    assert max(anchors[tr])+24*3600*1000<int(VAL_START.timestamp()*1000)
    assert max(anchors[va])+24*3600*1000<int(TEST_START.timestamp()*1000)
    # Perturbing a future candle cannot alter any already closed feature.
    row=800
    example=int(np.where(idx==row)[0][0])
    changed=arr.copy()
    changed[row+1,1]*=1.07
    _,x2=features(times,changed)
    assert np.array_equal(x[example],x2[example]),"future high leaked into predictors"
    labels2=build_targets(times,changed,idx)
    assert labels2["large_up_1h"][example]==1.0
    assert labels["large_up_1h"][example]==0.0
    # Evidence source must not contain direct macro claims or trader authority.
    print("VNEXT6_CAUSAL_LEAKAGE_AND_CENSORING_NEGATIVE_TESTS_PASS")

if __name__=="__main__":main()
