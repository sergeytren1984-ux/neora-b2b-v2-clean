from __future__ import annotations
import hashlib, json
from frozen_inference import forecast, frozen_artifact, calibrated_candidate_probabilities
from multi_horizon_features import compute, H4_FEATURES, H24_FEATURES

CLASSES=("upside","range","downside")

def forecast_with_continuity(candles, issued_at, artifact=None):
    artifact=artifact or frozen_artifact()
    primary=forecast(candles, issued_at, artifact)
    if all(primary[h]["probabilities"] is not None for h in ("4h","24h")):
        return primary
    features=compute(candles,issued_at)
    for horizon,names in (("4h",H4_FEATURES),("24h",H24_FEATURES)):
        if primary[horizon]["probabilities"] is not None:
            continue
        entry=artifact["horizons"][horizon]
        values=[float(features[name]) for name in names]
        raw_z=[(v-float(m))/float(s) for v,m,s in zip(values,entry["means"],entry["scales"])]
        limit=float(entry.get("max_abs_feature_z",4.0))
        clipped_z=[max(-limit,min(limit,z)) for z in raw_z]
        clipped=[{"feature":name,"raw_z":round(z,9),"clipped_z":round(cz,9)}
                 for name,z,cz in zip(names,raw_z,clipped_z) if z != cz]
        p=calibrated_candidate_probabilities(entry,clipped_z)
        primary[horizon]={
            "status":"DEGRADED_CLIPPED_DRIFT",
            "probabilities":dict(zip(CLASSES,[round(v,3) for v in p])),
            "feature_hash":hashlib.sha256(json.dumps(values,separators=(",",":")).encode()).hexdigest(),
            "continuity":{
                "primary_status":"ABSTAIN_MODEL_DRIFT",
                "method":"clip_standardized_features_to_registered_training_guard",
                "limit_abs_z":limit,
                "max_raw_abs_z":max(abs(z) for z in raw_z),
                "clipped_features":clipped,
            },
        }
    return primary
