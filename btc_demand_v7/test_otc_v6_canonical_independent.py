"""Negative test canonical JSON newline exactly equals registered v7R5 digest."""
import hashlib
from btc_demand_v7.otc_prospective_policy_v6 import digest
from btc_demand_v7.test_otc_prospective_policy_v6 import setup
from btc_demand_v7.otc_prospective_policy_v6 import compare_pair,precommitted_action

def main():
    expected=hashlib.sha256(b'{"x":1}'+bytes([10])).hexdigest()
    assert digest({"x":1})==expected, "source SHA digest differs from R5 canonical newline"
    event,delivery,raw=setup()
    assert compare_pair(event,delivery,raw)["precommitted_action"]=="BUY_NOW"
    assert precommitted_action(event,delivery["public_delivery_utc"])=="BUY_NOW"
    print("BTC_V7R5_OTC_V6_CANONICAL_NEWLINE_AND_CASHFLOW_NEGATIVE_PASS")

if __name__=="__main__":main()
