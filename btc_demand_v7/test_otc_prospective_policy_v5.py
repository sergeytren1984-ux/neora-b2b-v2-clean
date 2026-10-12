"""Adversarial OTC proxy acceptance tests: no future price feeds the action."""
import copy,datetime as dt
from btc_demand_v7.otc_prospective_policy_v5 import (
    MODEL_SHA,BUDGET,commitment,compare_pair,precommitted_action,simulated_execution)
from btc_demand_v7.otc_prospective_policy_v5 import digest

UTC=dt.timezone.utc
start=dt.datetime(2026,10,14,12,0,tzinfo=UTC)
pub=start+dt.timedelta(minutes=6)
close_start=pub.replace(second=0,microsecond=0)+dt.timedelta(minutes=1)
def setup(side="UP"):
    event={"schema":"btc-v7r3-signed-pressure-event-v1",
           "model_source_sha":MODEL_SHA,
           "slot_id":"20261014T120000Z",
           "anchor_utc":start.isoformat(),
           "issued_at_utc":(pub-dt.timedelta(minutes=1)).isoformat(),
           "status":"SIGNED_STATE_PUBLISHED","recovery":None,
           "diagnostic":{"alert":bool(side),"warning_side":side,"price_already_moved":False}}
    delivery={"slot_id":event["slot_id"],"source_signal_sha256":digest(event),
              "model_source_sha":MODEL_SHA,"public_delivery_utc":pub.isoformat()}
    baseline={"schema":"btc-v7r3-closed-1m-forward-source-v2",
              "symbol":"BTCUSDT","actual_publication_utc":pub.isoformat(),
              "reference_row":[int(close_start.timestamp()*1000)-120000,
                   "83000","83001","82999","83000","1",
                   int(close_start.timestamp()*1000)-60001]}
    raw=copy.deepcopy(baseline)
    raw["rows"]=[]
    t=int(close_start.timestamp()*1000)
    for i in range(240):
        end=t+(i+1)*60000
        px=83100 if i>=59 else 83000
        if i>=119:px=82800
        if i>=239:px=83400
        raw["rows"].append([end-60000,str(px),str(px+2),
                             str(px-2),str(px),"1",end-1])
    return event,delivery,raw

def rejects(fn,label):
    try:fn()
    except (ValueError,KeyError):
        print("REJECTED",label)
        return
    raise AssertionError("accepted illegal OTC test: "+label)

def main():
    assert commitment()["trading_authority"] is False
    event,delivery,raw=setup("UP")
    answer=compare_pair(event,delivery,raw)
    assert answer["precommitted_action"]=="BUY_NOW"
    assert answer["terminal_spot_after4h"]==83400.
    assert answer["buy_now_execution_spot_after1h"]==83100.
    assert answer["wait_execution_spot_after2h"]==82800.
    assert len(answer["scenarios"])==4
    assert not answer["actual_operator_quotes"]
    changed=copy.deepcopy(raw)
    changed["rows"][119][4]="82000";changed["rows"][119][1]="82000"
    changed["rows"][119][2]="84000";changed["rows"][119][3]="81990"
    assert precommitted_action(event,pub)==answer["precommitted_action"]
    reject_cash=simulated_execution(83000,84000,300,350)
    assert reject_cash["BTC"]==0 and reject_cash["USDT"]==BUDGET
    buy_cash=simulated_execution(83000,83050,500,350)
    assert abs(buy_cash["BTC"]*83400 - BUDGET)<BUDGET*.05
    wrong=copy.deepcopy(delivery)
    wrong["source_signal_sha256"]="0"*64
    rejects(lambda:compare_pair(event,wrong,raw),"forged signed delivery hash")
    bad=copy.deepcopy(raw);bad["rows"].pop(4)
    rejects(lambda:compare_pair(event,delivery,bad),"missing future minute")
    bad=copy.deepcopy(raw);bad["rows"][45][4]="NaN"
    rejects(lambda:compare_pair(event,delivery,bad),"nonfinite future close")
    event_down=copy.deepcopy(event);event_down["diagnostic"]["warning_side"]="DOWN"
    assert precommitted_action(event_down,pub)=="WAIT_1H"
    event_late=copy.deepcopy(event);event_late["issued_at_utc"]=(start+dt.timedelta(minutes=14)).isoformat()
    rejects(lambda:precommitted_action(event_late,pub),"backdated model computation")
    print("BTC_V7R5_PRECOMMITTED_OTC_ECONOMIC_PROXY_CASH_PRESERVATION_PASS")

if __name__=="__main__":main()
