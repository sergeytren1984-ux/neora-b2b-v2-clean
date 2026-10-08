"""Build the immutable vNext5 first-passage pre-start model package.

Historical folds have already been seen.  This script therefore makes no
historical skill claim.  It performs the final pre-start fit exactly once under
the frozen specification; only a future clean prospective epoch may select or
reject these candidates.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import joblib
import numpy as np
import sklearn
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from predictive_vnext4.core import (
    read_klines, build_15m_features, build_hourly_features,
    full_proba, _fit_hazard, _hazard_cumulative,
)
from research_vnext5 import predictive_research as r1
from research_vnext5 import predictive_research_r5_dev as r5

ROOT=Path(__file__).resolve().parents[1]
HERE=ROOT/"predictive_vnext5"
BUILD=HERE/"build"
BUILD.mkdir(parents=True,exist_ok=True)
SPEC=json.loads((HERE/"freeze_spec.json").read_text())
SEED=20261008


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fit_calibrator(raw,y):
    m=LogisticRegression(C=.05,max_iter=500)
    m.fit(np.log(np.clip(raw,1e-8,1.0)),y)
    return m


def final_masks(dates,due,head):
    cutoff=np.datetime64("2026-07-01T00:00:00")
    end=np.datetime64(
        "2026-10-01T00:00:00" if head in ("1h","4h")
        else "2026-09-25T00:00:00"
    )
    due_dates=dates+due
    train=due_dates<cutoff
    cal=(dates>=cutoff)&(due_dates<end)
    if int(np.sum(train))<500 or int(np.sum(cal))<100:
        raise RuntimeError(f"insufficient final fit rows for {head}")
    return train,cal


def fit_classifier(X,y,train,cal):
    logistic=make_pipeline(
        StandardScaler(),
        LogisticRegression(C=.03,max_iter=500),
    )
    logistic.fit(X[train],y[train])
    lcal=fit_calibrator(full_proba(logistic,X[cal]),y[cal])

    gbdt=HistGradientBoostingClassifier(
        max_iter=120,max_leaf_nodes=15,min_samples_leaf=100,
        learning_rate=.04,l2_regularization=12,random_state=SEED,
    )
    gbdt.fit(X[train],y[train])
    gcal=fit_calibrator(full_proba(gbdt,X[cal]),y[cal])
    return {
        "logistic":{"model":logistic,"calibrator":lcal},
        "gbdt":{"model":gbdt,"calibrator":gcal},
    }


def common(head,source_sha,feature_names,train,cal,vol_name):
    return {
        "schema":"btc-predictive-vnext5-frozen-first-passage-head-v1",
        "status":"FROZEN_PRESTART_CANDIDATE",
        "head":head,
        "raw_classes":list(r1.RAW_ZONE_CLASSES),
        "display_classes":["DOWN","RANGE","UP"],
        "display_mapping":{
            "DOWN":"LOWER_FIRST + 0.5 * AMBIGUOUS_SAME_BAR",
            "RANGE":"NEITHER",
            "UP":"UPPER_FIRST + 0.5 * AMBIGUOUS_SAME_BAR",
        },
        "feature_names":list(feature_names)+[
            "lower_barrier_sigma","upper_barrier_sigma",
            "barrier_sigma_asymmetry","log_lower_to_upper_sigma_ratio",
        ],
        "base_feature_count":len(feature_names),
        "volatility_feature_name":vol_name,
        "barrier_domain":SPEC["target_contract"]["custom_zone_domain"],
        "training_barrier_sigma_pairs":
            SPEC["target_contract"]["training_barrier_sigma_pairs"],
        "training_contract":{
            **SPEC["final_fit_contract"],
            "train_n":int(np.sum(train)),
            "calibration_n":int(np.sum(cal)),
        },
        "source_sha256":source_sha,
        "numpy_version":np.__version__,
        "sklearn_version":sklearn.__version__,
        "prospective_skill_proven":False,
        "trading_authority":False,
    }


def build_15m_head(head,bars):
    path=ROOT/"research_vnext4r6/data/BTCUSDT_15m_2024-01_2026-09.json.gz"
    t,o,hi,lo,c,v,trades,taker,source_sha=read_klines(path,900000)
    ix,dates,X,names,regime,vol=build_15m_features(
        t,hi,lo,c,v,trades,taker,16
    )
    ZX,zy,zd,zr,zv,zpid,due=r1.zone_augmented_dataset(
        X,dates,regime,vol,ix,c,hi,lo,bars,np.timedelta64(bars*15,"m")
    )
    train,cal=final_masks(zd,due,head)
    artifact=common(head,source_sha,names,train,cal,"std_4h")
    artifact.update({
        "role":"CHAMPION_CANDIDATE",
        "architecture":"calibrated_logistic_plus_calibrated_gbdt_equal_weight",
        "horizon_steps":bars,
        "source_interval":"15m",
        "models":fit_classifier(ZX,zy,train,cal),
        "class_count_train":
            np.bincount(zy[train],minlength=4).astype(int).tolist(),
        "class_count_calibration":
            np.bincount(zy[cal],minlength=4).astype(int).tolist(),
    })
    last_base=X[-1].tolist()
    return artifact,last_base,float(vol[-1])


def build_24h():
    path=ROOT/"btc_1h_2024_to_sep24_2026.json"
    t,o,hi,lo,c,v,trades,taker,source_sha=read_klines(path,3600000)
    ix,dates,X,names,regime,vol,atr=build_hourly_features(
        t,hi,lo,c,v,trades,taker,24
    )
    due=np.timedelta64(24,"h")
    ZX,zy,zd,zr,zv,zpid,_=r1.zone_augmented_dataset(
        X,dates,regime,vol,ix,c,hi,lo,24,due
    )
    train,cal=final_masks(zd,due,"24h")
    classifier=common("24h",source_sha,names,train,cal,"std_24h")
    classifier.update({
        "role":"CHALLENGER_NO_WINNER",
        "candidate_id":"24h_classifier",
        "architecture":"calibrated_logistic_plus_calibrated_gbdt_equal_weight",
        "horizon_steps":24,
        "source_interval":"1h",
        "models":fit_classifier(ZX,zy,train,cal),
        "class_count_train":
            np.bincount(zy[train],minlength=4).astype(int).tolist(),
        "class_count_calibration":
            np.bincount(zy[cal],minlength=4).astype(int).tolist(),
    })

    HX,hy,hw,hd,hv,hpid=r5.zone_augmented_with_when(
        X,dates,regime,vol,ix,c,hi,lo
    )
    htrain,hcal=final_masks(hd,due,"24h")
    hazard_model=_fit_hazard(HX,hy,hw,htrain,24,3)
    hraw=_hazard_cumulative(hazard_model,HX[hcal],24,3)
    hazard_cal=fit_calibrator(hraw,hy[hcal])
    hazard=common("24h",source_sha,names,htrain,hcal,"std_24h")
    hazard.update({
        "role":"CHALLENGER_NO_WINNER",
        "candidate_id":"24h_competing_risks",
        "architecture":"discrete_time_competing_risks_hazard_calibrated",
        "horizon_steps":24,
        "hazard_step":3,
        "source_interval":"1h",
        "model":hazard_model,
        "calibrator":hazard_cal,
        "class_count_train":
            np.bincount(hy[htrain],minlength=4).astype(int).tolist(),
        "class_count_calibration":
            np.bincount(hy[hcal],minlength=4).astype(int).tolist(),
    })
    return classifier,hazard,X[-1].tolist(),float(vol[-1])


def dump(name,obj):
    p=BUILD/name
    joblib.dump(obj,p,compress=3)
    return p


def main():
    a1,v1,vol1=build_15m_head("1h",4)
    a4,v4,vol4=build_15m_head("4h",16)
    c24,h24,v24,vol24=build_24h()
    paths={
        "1h":dump("head_1h_classifier.joblib",a1),
        "4h":dump("head_4h_classifier.joblib",a4),
        "24h_classifier":dump("head_24h_classifier.joblib",c24),
        "24h_competing_risks":dump("head_24h_competing_risks.joblib",h24),
    }
    vectors={
        "1h":{"base_features":v1,"vol":vol1,"horizon_steps":4},
        "4h":{"base_features":v4,"vol":vol4,"horizon_steps":16},
        "24h":{"base_features":v24,"vol":vol24,"horizon_steps":24},
    }
    (BUILD/"selftest_vectors.json").write_text(
        json.dumps(vectors,indent=2,sort_keys=True)+"\n"
    )
    manifest={
        "schema":"btc-predictive-vnext5-first-passage-artifact-manifest-v1",
        "status":"FROZEN_PRESTART_ARTIFACT_PACKAGE",
        "freeze_spec_sha256":sha(HERE/"freeze_spec.json"),
        "prospective_protocol_sha256":sha(HERE/"prospective_protocol.json"),
        "parent_engineering_source_sha":
            SPEC["parent_engineering_source_sha"],
        "artifacts":{
            k:{
                "path":str(v.relative_to(ROOT)),
                "sha256":sha(v),
            } for k,v in paths.items()
        },
        "selftest_vectors_sha256":sha(BUILD/"selftest_vectors.json"),
        "historical_selection_exhausted":True,
        "next_valid_selection_evidence":"CLEAN_PROSPECTIVE_EPOCH",
        "start_utc":None,
        "prospective_skill_proven":False,
        "trading_authority":False,
    }
    (BUILD/"freeze_manifest.json").write_text(
        json.dumps(manifest,indent=2,sort_keys=True)+"\n"
    )
    print(json.dumps(manifest,indent=2,sort_keys=True))


if __name__=="__main__":
    main()
