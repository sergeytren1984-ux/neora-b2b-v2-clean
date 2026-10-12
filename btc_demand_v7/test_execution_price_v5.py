"""Negative temporal causality and raw source tests for ONE price challenger."""
from __future__ import annotations
import datetime as dt,math
import numpy as np
from btc_demand_v7.execution_price_v5 import (
    strict_spot,make_target,split,EMBARGO_MS,VAL_START,TEST_START,STEP)
from btc_skill_rebuild.evaluate import build_arrays,features

UTC=dt.timezone.utc
def bad(fn,label):
    try:fn()
    except (ValueError,AssertionError):
        print("REJECTED",label)
        return
    raise AssertionError("accepted invalid "+label)

def rows_from(n):
    origin=int(dt.datetime(2026,8,1,tzinfo=UTC).timestamp()*1000)
    result=[]
    for i in range(n):
        t=origin+i*STEP
        spot=84000+12*i
        result.append([t,str(spot),str(spot+50),str(spot-50),
            str(spot+5),"10",t+STEP-1,"840050",100,"6","504030","0"])
    return result

def run():
    # Raw guard cannot hide future-data, noninteger trades or corrupted
    # Binance taker share behind median/MAD imputation.
    raw=rows_from(12001);strict_spot(raw)
    corrupted=raw.copy();corrupted[1]=raw[1].copy()
    corrupted[1][8]="NaN"
    bad(lambda:strict_spot(corrupted),"historical NaN trades")
    corrupted[1][8]="1.1"
    bad(lambda:strict_spot(corrupted),"fractional trade count")
    corrupted[1][8]="100"
    corrupted[1][0]=corrupted[0][0]
    bad(lambda:strict_spot(corrupted),"historical duplicate candle")
    short=rows_from(650)
    t,a=build_arrays(short)
    ids,x=features(t,a)
    before=x[0].copy()
    changed=[r.copy() for r in short]
    for i in range(590,650):changed[i][4]=str(float(changed[i][4])+5000)
    _,changed_array=build_arrays(changed)
    _,x_after=features(t,changed_array)
    assert np.array_equal(before,x_after[0])
    start=int(dt.datetime(2026,8,1,tzinfo=UTC).timestamp()*1000)
    idx=np.array([576,577,578])
    y,steps=make_target(t,a,idx,"1h")
    assert all(steps==12)
    assert all(np.isfinite(y))
    moment=dt.datetime(2026,8,1,4,55,tzinfo=UTC)
    mindex=int((moment.timestamp()*1000-start)//STEP)-1
    if mindex>=0:
        _,morning_steps=make_target(t,a,np.array([mindex]),"morning_08msk")
        assert morning_steps[0]>=1
    # Full 65d grid: label end PLUS 30h embargo must precede next cohort.
    begin=int(dt.datetime(2026,8,1,tzinfo=UTC).timestamp()*1000)
    anchor=np.arange(begin,begin+68*24*3600*1000,STEP,dtype=np.int64)
    off=np.full(len(anchor),300,dtype=np.int64)
    train,valid,test=split(anchor,off)
    v=int(VAL_START.timestamp()*1000);te=int(TEST_START.timestamp()*1000)
    assert np.all(anchor[train]+off[train]*STEP+EMBARGO_MS<v)
    assert np.all(anchor[valid]>=v)
    assert np.all(anchor[valid]+off[valid]*STEP+EMBARGO_MS<te)
    assert np.all(anchor[test]>=te)
    bad(lambda:split(anchor[:5],off[:5]),"insufficient training phase")
    print("BTC_V7R5_EXECUTION_PRICE_CAUSAL_EMBARGO_AND_SIGNED_SOURCE_NEGATIVE_TESTS_PASS")

if __name__=="__main__":run()
