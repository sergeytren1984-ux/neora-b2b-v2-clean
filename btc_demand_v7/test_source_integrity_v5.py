"""Attack real, separately verified Cosign-signed Binance+OKX snapshot bytes.

This test does not itself authenticate Sigstore; the preceding GitHub job
independently verifies signed snapshot publisher identity, SHA and Rekor proof.
It then exercises numerical raw -> factor replay, not model skill.
"""
from __future__ import annotations
import copy,json,os
from btc_demand_v7.source_integrity_v5 import rederive

def reject(source,how,name):
    altered=copy.deepcopy(source)
    how(altered)
    try:rederive(altered)
    except (ValueError,TypeError,KeyError,IndexError) as exc:
        print("SOURCE_REPLAY_REJECTED",name,type(exc).__name__)
        return
    raise AssertionError("malicious unsigned derived source accepted "+name)

def run():
    path=os.environ.get("BTC_V7R5_SIGNED_RAW_SNAPSHOT")
    if not path:raise ValueError("real previously signed source required")
    original=json.load(open(path))
    proof=rederive(original)
    assert proof["numerically_recomputed_from_signed_raw"]
    assert proof["oi_available"] and proof["book_available"]
    assert proof["pressure_factor_ready"]
    assert proof["model_skill_proven"] is False
    reject(original,lambda d:d["observation"]["oi"].__setitem__(
        "oi_change_15m_pct",d["observation"]["oi"]["oi_change_15m_pct"]+5),
        "fabricated OKX OI 15m delta")
    reject(original,lambda d:d["observation"]["book"].__setitem__(
        "top10_size_imbalance",-d["observation"]["book"]["top10_size_imbalance"]),
        "fabricated directional order book pressure")
    reject(original,lambda d:d["observation"]["microflow"].__setitem__(
        "recent3_taker_buy_fraction",0.94),
        "fabricated current 3m aggressive-buy fraction")
    reject(original,lambda d:d["observation"].__setitem__(
        "15m_taker_buy_fraction",.98),
        "fabricated 15m spot taker")
    reject(original,lambda d:d["observation"].__setitem__("oi",None),
        "secretly suppressed otherwise valid optional OI")
    reject(original,lambda d:d["observation"].__setitem__("book",None),
        "secretly suppressed otherwise valid optional depth")
    reject(original,lambda d:d["raw_optional"]["oi_okx"]["data"][0].__setitem__(
        1,str(float(d["raw_optional"]["oi_okx"]["data"][0][1])*1.05)),
        "mutated source OI USD while derivative context unchanged")
    reject(original,lambda d:d["optional_receipts"]["book_okx"].__setitem__(
        "response_received_ms",
        d["optional_receipts"]["book_okx"]["response_received_ms"]+24*3600*1000),
        "book receipt from next day")
    reject(original,lambda d:d["optional_receipts"]["book_okx"]["query"].__setitem__(
        "instId","ETH-USDT-SWAP"),"cross-instrument order book")
    reject(original,lambda d:d["microflow_rows"][-1].__setitem__(
        9,str(float(d["microflow_rows"][-1][9])*.5)),
        "recomputed 1m flow differs from signed claimed 3m summary")
    print("BTC_V7R5_REAL_SIGNED_SOURCE_OKX_OI_BOOK_BINANCE_1M_5M_REPLAY_AND_TAMPER_TESTS_PASS",
          {k:proof[k] for k in ("anchor_utc","spot_reference_price",
                                "contemporary_3m_taker_buy_fraction",
                                "oi_available","book_available")})

if __name__=="__main__":run()
