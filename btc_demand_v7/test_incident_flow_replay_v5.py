"""Adversarial causal 1m flow spot-only incident ablation tests."""
import datetime as dt,copy
from btc_demand_v7.incident_flow_replay_v5 import early_pressure,prospective_60m_counterfactual
UTC=dt.timezone.utc

def build():
    origin=int(dt.datetime(2026,10,14,tzinfo=UTC).timestamp()*1000)
    result=[]
    for i in range(130):
        t=origin+i*60000
        size=(45. if 18<=i<=20 else 10.)
        buy=(.8 if 18<=i<=20 else .5)
        result.append([t,"83000","83005","82995","83000",str(size),
                       t+59999,"830000",100,str(size*buy),"830000","0"])
    return result

def run():
    raw=build()
    detection=early_pressure(raw,20)
    assert detection is not None and detection["direction"]=="UP"
    assert detection["taker_buy_fraction_3m"]>.7
    assert detection["volume_3m_vs_previous_3m"]>2.5
    unrelated=copy.deepcopy(raw)
    unrelated[43][4]="90000";unrelated[43][2]="90100"
    assert early_pressure(unrelated,20)==detection
    # A real +500 future barrier at the beginning of minute delivery+23
    # has only 22-min lower-bound lead, not 60 minutes.
    target=20+2+23
    raw[target][2]="83600"
    result=prospective_60m_counterfactual(raw,20,detection)
    assert result["barriers"]["500"]["outcome"]=="UP"
    assert result["barriers"]["500"]["correct_early_direction"] is True
    assert result["barriers"]["500"]["conservative_lead_minutes"]==22
    assert result["barriers"]["500"]["OTC_60min_advance_proven"] is False
    # After-candle but before public-delivery +1% jump: invalid early credit.
    late=build()
    late[22][4]="83850";late[22][2]="83860"
    for i in range(23,len(late)):
        late[i][1]="83850";late[i][2]="83860"
        late[i][3]="83840";late[i][4]="83850"
    late_result=prospective_60m_counterfactual(late,20,detection)
    assert late_result["delivery_status"]=="MOVED_BEFORE_DELIVERY"
    assert late_result["barriers"]["500"]["correct_early_direction"] is False
    # Trade-flow signal cannot depend on future event labels.
    moved=copy.deepcopy(raw)
    for i in range(22,len(moved)):
        moved[i][4]="83200"
    assert early_pressure(moved,20)==detection
    print("BTC_V7R5_ONE_MINUTE_FLOW_CAUSAL_LATENCY_AND_TRUE_PREMOVE_LEAD_PASS")

if __name__=="__main__":run()
