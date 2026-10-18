"""Read-only research eligibility gate for immutable v7R6 published probabilities.

Compares published distributions with the EXACT pinned pre-epoch predictor.
A valid prospective publication is not necessarily a valid output of that
predictor. Never substitute the ex-post recomputation for a public forecast.
"""
from __future__ import annotations
import argparse,datetime as dt,hashlib,json,math,pathlib
from btc_skill_rebuild.research_signed_spot_forward_v7r6 import asof_last_feature
from btc_skill_rebuild.research_endpoint_24h_v7r6 import predict

PINNED_WEIGHTS_BLOB="05e61325250fbd470c988326cbeaf24853bd6947"
PINNED_FORECASTER_BLOB="9709e5c8b886f4f362fd003d0af91f74e3e9dc38"
PINNED_PREDICT_BLOB="39ce2baec7b539be8adbe5ca454984ca5b9c5252"
PINNED_NORMALIZE_BLOB="e5806efd677f5bff31b49c035f521a048da8976c"
TOL=1e-12

def git_blob_sha1(raw):
    return hashlib.sha1(("blob "+str(len(raw))).encode()+bytes([0])+raw).hexdigest()

def read_pinned(path,expected):
    raw=pathlib.Path(path).read_bytes()
    if git_blob_sha1(raw)!=expected:
        raise ValueError("pinned immutable research source changed: "+str(path))
    return json.loads(raw)

def parity(snapshot,public,weights):
    if snapshot.get("schema")!="btc-v7-live-shadow-snapshot-v1":
        raise ValueError("wrong R5 source schema")
    if public.get("schema")!="btc-v7r6-unpromoted-ex-ante-research-spot-probabilities-v1":
        raise ValueError("wrong research forecast schema")
    slot,feature,reference=asof_last_feature(snapshot["five_min_rows"])
    anchor=dt.datetime.fromtimestamp(slot/1000,dt.timezone.utc)
    if (anchor!=dt.datetime.fromisoformat(snapshot["anchor_utc"].replace("Z","+00:00"))
        or anchor!=dt.datetime.fromisoformat(public["clock_anchor_utc"].replace("Z","+00:00"))):
        raise ValueError("R5 as-of source not at published forecast anchor")
    if len(feature)!=17:raise ValueError("feature schema changed")
    checks={}
    for h in ("1h","4h","24h"):
        head=weights["heads"][h]
        alpha=head["validation_selected_shrink"]
        original=predict(head["model_parameters"],feature,alpha)
        inverse=predict(head["model_parameters"],feature,1-alpha)
        pub=[float(public["three_way"][h][k]) for k in ("up","down","range")]
        if not all(math.isfinite(x) and 0<=x<=1 for x in pub) or abs(sum(pub)-1)>TOL:
            raise ValueError("invalid published probability")
        if abs(float(public["three_way"][h]["reference_spot_usdt"])-reference)>1e-7:
            raise ValueError("published reference price differs from as-of source")
        err=max(abs(a-b) for a,b in zip(pub,original))
        inverted=max(abs(a-b) for a,b in zip(pub,inverse))
        checks[h]={"pinned_validation_alpha":alpha,
                   "max_abs_original_code_error":err,
                   "max_abs_inverted_alpha_error":inverted,
                   "matches_original_pinned_code":err<=TOL,
                   "matches_inverted_alpha":inverted<=TOL,
                   "published_probabilities":pub,
                   "unpublished_original_code_probabilities":original}
    eligible=all(v["matches_original_pinned_code"] for v in checks.values())
    return {"schema":"btc-v7r6-original-pinned-math-parity-gate-v1",
            "anchor_utc":anchor.isoformat(),
            "horizons":checks,
            "eligible_for_original_pinned_code_skill":eligible,
            "not_independently_cosign_verified":True,
            "may_not_rewrite_original_published_probabilities":True,
            "trading_authority":False}

def main():
    p=argparse.ArgumentParser()
    for key in ("snapshot","forecast","weights","out"):
        p.add_argument("--"+key,required=True)
    a=p.parse_args()
    weights=read_pinned(a.weights,PINNED_WEIGHTS_BLOB)
    if git_blob_sha1(pathlib.Path(__import__("btc_skill_rebuild.research_signed_spot_forward_v7r6",fromlist=["x"]).__file__).read_bytes())!=PINNED_FORECASTER_BLOB:
        raise ValueError("feature equation differs from pinned original")
    if git_blob_sha1(pathlib.Path(__import__("btc_skill_rebuild.research_endpoint_24h_v7r6",fromlist=["x"]).__file__).read_bytes())!=PINNED_PREDICT_BLOB:
        raise ValueError("softmax equation differs from pinned original")
    if git_blob_sha1(pathlib.Path(__import__("btc_skill_rebuild.research_competing_barriers_v7r6",fromlist=["x"]).__file__).read_bytes())!=PINNED_NORMALIZE_BLOB:
        raise ValueError("normalization equation differs from pinned original")
    snapshot=json.loads(pathlib.Path(a.snapshot).read_text())
    public=json.loads(pathlib.Path(a.forecast).read_text())
    if git_blob_sha1(pathlib.Path(a.snapshot).read_bytes())!=public["input_R5_spot_source_blob_GitHub_sha1"]:
        raise ValueError("R5 snapshot does not match original forecast cited blob")
    result=parity(snapshot,public,weights)
    pathlib.Path(a.out).write_text(json.dumps(result,indent=2,sort_keys=True)+chr(10))
    print("PINNED_FORECAST_ELIGIBLE",result["eligible_for_original_pinned_code_skill"])
    for h,r in result["horizons"].items():
        print(h,"original_error",r["max_abs_original_code_error"],
              "inverse_error",r["max_abs_inverted_alpha_error"])

if __name__=="__main__":main()
