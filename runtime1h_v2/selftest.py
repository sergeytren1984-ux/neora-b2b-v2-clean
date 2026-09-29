from __future__ import annotations
import gzip, json, sys
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"runtime1h_v2"))
from inference import forecast_1h
from worker import closed

UTC=timezone.utc
ANCHOR=datetime(2026,9,29,16,0,tzinfo=UTC)
EXPECTED={
    "upside":0.215129,
    "range":0.603875,
    "downside":0.180996,
}
EXPECTED_HASH="a88b8013722a18b9fd601c8eb2c6b8a85bdc665100dce370696ddcfe9248393e"

def fixture_raw():
    bundle=json.loads(gzip.decompress((ROOT/"raw/20260929T160000Z.json.gz").read_bytes()))
    return json.loads(bundle["captures"][0]["raw"])

def main():
    raw=fixture_raw()
    candles=closed(raw,3600,ANCHOR,169)
    out=forecast_1h(candles)
    if out["probabilities"]!=EXPECTED:
        raise AssertionError((out["probabilities"],EXPECTED))
    if out["feature_hash"]!=EXPECTED_HASH:
        raise AssertionError((out["feature_hash"],EXPECTED_HASH))

    # Remove an admitted historical candle while preserving enough rows overall.
    # The final close remains correct; fail-closed continuity must still reject.
    admitted_open=int(datetime.fromisoformat(candles[-100]["open_time"]).timestamp()*1000)
    tampered=[x for x in raw if int(x[0])!=admitted_open]
    try:
        closed(tampered,3600,ANCHOR,169)
    except ValueError as exc:
        if "noncontiguous" not in str(exc):
            raise
    else:
        raise AssertionError("gap was accepted")

    print(json.dumps({"status":"PASS","probabilities":out["probabilities"],
                      "feature_hash":out["feature_hash"],"gap_rejected":True},sort_keys=True))

if __name__=="__main__": main()
