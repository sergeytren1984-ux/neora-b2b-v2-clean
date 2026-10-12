"""Adversarial replay of the expert's timing, source and signed-release defects."""
from __future__ import annotations
import copy,datetime as dt,json,math,pathlib,shutil,tempfile
from joblib import load
from btc_demand_v7.infer_live import issue
from btc_demand_v7.release_guard import check

def rejected(call,label):
    try:call()
    except (ValueError,RuntimeError,KeyError,OverflowError):
        print("REJECTED",label)
        return
    raise AssertionError("adversarial input accepted: "+label)

def main(root,snapshot_path,release_path):
    root=pathlib.Path(root)
    binding=check(root,release_path)
    print("RELEASE_PIN_VERIFIED",binding["source_commit_sha"])
    original=json.loads(pathlib.Path(snapshot_path).read_text())
    model=load(root/"candidate.joblib")
    residual=json.loads((root/"spot_paired_validation_errors.json").read_text())
    audit=json.loads((root/"audit.json").read_text())
    now=dt.datetime.fromisoformat(original["retrieved_at_utc"])+dt.timedelta(seconds=5)
    success=issue(original,model,residual,audit,now=now)
    assert success["otc_comparison"]["status"]=="NO_EXECUTION_ALIGNED_FORECAST"
    assert all(x["acquired_btc"] is None for x in success["otc_comparison"]["actions"].values())
    assert all(k in success["price_exact_target_utc"] for k in ("1h","2h","4h","5h","morning","morning_plus_1h"))
    print("HISTORICAL_NORMAL_REPLAY_BLOCKS_MISALIGNED_OTC")

    def mutate(label,change):
        bad=copy.deepcopy(original)
        change(bad)
        rejected(lambda:issue(bad,model,residual,audit,now=now),label)
    mutate("wrong instrument",lambda d:d.__setitem__("symbol","ETHUSDT"))
    mutate("wrong required feed",lambda d:d.__setitem__("raw_source","unknown"))
    mutate("future raw5m close",lambda d:d["five_min_rows"][-1].__setitem__(6,int(d["five_min_rows"][-1][6])+86_400_000))
    mutate("future raw1m close",lambda d:d["one_min_rows"][-1].__setitem__(6,int(d["one_min_rows"][-1][6])+86_400_000))
    mutate("missing middle 5m candle",lambda d:d["five_min_rows"].pop(220))
    mutate("full 1m raw timestamp drift",lambda d:[(r.__setitem__(0,int(r[0])+86_400_000),r.__setitem__(6,int(r[6])+86_400_000)) for r in d["one_min_rows"]])
    mutate("fabricated spot observation",lambda d:d["observation"].__setitem__("reference_spot",float(d["observation"]["reference_spot"])+100))
    mutate("snapshot receipt earlier than anchor",lambda d:d.__setitem__("retrieved_at_utc",(dt.datetime.fromisoformat(d["anchor_utc"])-dt.timedelta(seconds=1)).isoformat()))
    mutate("snapshot receipt after issue",lambda d:d.__setitem__("retrieved_at_utc",(now+dt.timedelta(seconds=1)).isoformat()))
    rejected(lambda:issue(original,model,residual,audit,now=now+dt.timedelta(minutes=25)),"stale publication")
    with tempfile.TemporaryDirectory() as folder:
        tmp=pathlib.Path(folder)
        for p in root.iterdir():
            if p.is_file() and (p.name in ("candidate.joblib","audit.json","spot_paired_validation_errors.json") or p.name.endswith(".sigstore.json")):
                shutil.copy2(p,tmp/p.name)
        altered=tmp/"candidate.joblib"
        blob=bytearray(altered.read_bytes());blob[-1]^=1;altered.write_bytes(blob)
        rejected(lambda:check(tmp,release_path),"mixed source signed payload")
    print("V7R1_ADVERSARIAL_INFERENCE_PROVENANCE_PASS")

if __name__=="__main__":
    import sys
    if len(sys.argv)!=4:
        raise SystemExit("python -m btc_demand_v7.test_remediation ROOT SNAPSHOT_JSON TRUSTED_RELEASE")
    main(sys.argv[1],sys.argv[2],sys.argv[3])
