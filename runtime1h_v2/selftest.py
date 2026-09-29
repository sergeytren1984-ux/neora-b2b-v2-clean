from __future__ import annotations
import gzip, json, math, sys
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"runtime1h_v2"))
from inference import feature_values, forecast_1h
from worker import closed

UTC=timezone.utc
ANCHOR=datetime(2026,9,29,16,0,tzinfo=UTC)
EXPECTED={
    "upside":0.21512915194804402,
    "range":0.6038746380912332,
    "downside":0.18099620996072271,
}
EXPECTED_EMA_FEATURES=(-0.792393248752643,-0.014062974566109165)

def fixture_raw():
    bundle=json.loads(gzip.decompress((ROOT/"raw/20260929T160000Z.json.gz").read_bytes()))
    return json.loads(bundle["captures"][0]["raw"])

def main():
    raw=fixture_raw()
    candles=closed(raw,3600,ANCHOR,169)
    vals=feature_values(candles)
    for got,want in zip((vals[5],vals[6]),EXPECTED_EMA_FEATURES):
        if not math.isclose(got,want,rel_tol=0.0,abs_tol=1e-10):
            raise AssertionError(("EMA contract mismatch",got,want))
    out=forecast_1h(candles)
    for k,want in EXPECTED.items():
        got=out["probabilities"][k]
        if not math.isclose(got,want,rel_tol=0.0,abs_tol=1e-6):
            raise AssertionError(("probability mismatch",k,got,want))

    admitted_open=int(datetime.fromisoformat(candles[-100]["open_time"]).timestamp()*1000)
    tampered=[x for x in raw if int(x[0])!=admitted_open]
    try:
        closed(tampered,3600,ANCHOR,169)
    except ValueError as exc:
        if "noncontiguous" not in str(exc):
            raise
    else:
        raise AssertionError("gap was accepted")

    print(json.dumps({
        "status":"PASS",
        "probabilities":out["probabilities"],
        "ema_feature_values":[vals[5],vals[6]],
        "feature_hash":out["feature_hash"],
        "gap_rejected":True,
    },sort_keys=True))

if __name__=="__main__": main()
