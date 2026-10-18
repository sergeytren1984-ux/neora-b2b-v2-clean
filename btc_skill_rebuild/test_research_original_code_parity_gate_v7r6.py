"""Negative controls for frozen mathematical forecast eligibility."""
import datetime as dt,json,pathlib
from btc_skill_rebuild.research_original_code_parity_gate_v7r6 import parity
from btc_skill_rebuild.research_signed_spot_forward_v7r6 import asof_last_feature
from btc_skill_rebuild.research_endpoint_24h_v7r6 import predict

def case(invert=False):
    anchor=dt.datetime(2026,10,18,4,tzinfo=dt.timezone.utc)
    start=int(anchor.timestamp()*1000)-310*300000
    rows=[]
    for i in range(310):
        t=start+i*300000
        rows.append([t,"82000","82001","81999","82000","12",t+299999,"0",120,"6","0","0"])
    s={"schema":"btc-v7-live-shadow-snapshot-v1",
       "anchor_utc":anchor.isoformat(),"five_min_rows":rows}
    _,x,price=asof_last_feature(rows)
    weights=json.loads((pathlib.Path(__file__).parent/"prospective_shadow"/
          "frozen_historical_weights_first_asof_20261013.json").read_text())
    p={}
    for h,e in weights["heads"].items():
        alpha=e["validation_selected_shrink"]
        v=predict(e["model_parameters"],x,1-alpha if invert else alpha)
        p[h]={"up":v[0],"down":v[1],"range":v[2],"reference_spot_usdt":price}
    f={"schema":"btc-v7r6-unpromoted-ex-ante-research-spot-probabilities-v1",
       "clock_anchor_utc":anchor.isoformat(),"three_way":p}
    return s,f,weights

def must_reject(fn):
    try:fn()
    except ValueError:return
    raise AssertionError("invalid source was accepted")

def main():
    s,f,w=case()
    assert parity(s,f,w)["eligible_for_original_pinned_code_skill"]
    s,f,w=case(True)
    assert not parity(s,f,w)["eligible_for_original_pinned_code_skill"]
    assert all(v["matches_inverted_alpha"] for v in parity(s,f,w)["horizons"].values())
    s,f,w=case();s["anchor_utc"]="2026-10-18T05:00:00+00:00"
    must_reject(lambda:parity(s,f,w))
    s,f,w=case();f["three_way"]["1h"]["reference_spot_usdt"]+=1
    must_reject(lambda:parity(s,f,w))
    s,f,w=case();f["three_way"]["4h"]["range"]+=.01
    must_reject(lambda:parity(s,f,w))
    s,f,w=case();s["five_min_rows"][300][0]+=60000
    must_reject(lambda:parity(s,f,w))
    print("PINNED_ALPHA_RESEARCH_POSITIVE_AND_NEGATIVE_TESTS_PASS")

if __name__=="__main__":main()
