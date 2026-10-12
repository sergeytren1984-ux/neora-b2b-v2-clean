"""Synthetic counterexample tests for one true >=60m actionable risk classifier."""
import copy,datetime as dt,math
from btc_demand_v7.execution_hazard_v5 import (
    feat,label,phase,V_START,T_START,PREHISTORY,LATENCY,TARGET_MINUTES)

UTC=dt.timezone.utc
def make():
    begin=int(dt.datetime(2026,10,13,tzinfo=UTC).timestamp()*1000)
    rows=[]
    for i in range(300):
        t=begin+i*60000
        rows.append([t,"83000","83010","82990","83000","10",
                     t+59999,"830000",200,"6","498000","0"])
    return rows

def main():
    i=90
    fresh=make()
    x=feat(fresh,i)
    assert len(x)==14 and all(map(math.isfinite,x))
    future=copy.deepcopy(fresh)
    future[i+10][2]="85100";future[i+10][4]="85000"
    assert feat(future,i)==x # no future candle enters input
    first=make()
    at=i+LATENCY+61
    first[at][2]="83600"
    y,early,lead=label(first,i)
    assert (y,early,lead)==(1,True,60),(y,early,lead)
    too_early=make()
    at=i+LATENCY+60
    too_early[at][2]="83600"
    y,early,lead=label(too_early,i)
    assert (y,early,lead)==(0,True,59),(y,early,lead)
    down=make()
    down[i+LATENCY+61][3]="82400"
    assert label(down,i)==(2,True,60)
    same=make()
    same[i+LATENCY+61][2]="83600"
    same[i+LATENCY+61][3]="82400"
    assert label(same,i)==(0,True,60)
    after_public=make()
    after_public[i+LATENCY][4]="83900"
    assert label(after_public,i)==(0,False,None)
    assert phase(V_START-dt.timedelta(days=3),122)=="TRAIN"
    assert phase(T_START+dt.timedelta(minutes=5),122)=="SEEN_TEST"
    print("BTC_V7R5_SINGLE_3CLASS_HAZARD_ACTUAL_60MIN_OTC_LEAD_AND_NO_FUTURE_FEATURES_PASS")

if __name__=="__main__":main()
