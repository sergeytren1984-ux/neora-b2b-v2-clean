"""Evaluate frozen R6 research-selection policy. No model training occurs here."""
from __future__ import annotations
import json,math
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
D=ROOT/"research_vnext4r6"

def load(name):
    p=D/name
    if not p.exists(): raise FileNotFoundError(name)
    return json.loads(p.read_text())

def main():
    policy=load("acceptance_policy.json")
    s=load("structural_result.json")
    macro=load("macro_ablation_result.json")
    deriv=load("derivatives_ablation_result.json")
    memory=load("breakout_memory_result.json")

    hgate=policy["core_head_gate"];tgate=policy["target_gate"]
    core={};all_core=True
    for head in hgate["required_heads"]:
        z=s["heads"][head];base=z["summary"]["vol90d"]
        foldn=len(z["folds"])
        target=z["target"];q=target["distance_ratio_quantiles"];median=float(q[2])
        target_ok=tgate["median_distance_ratio_min"]<=median<=tgate["median_distance_ratio_max"]
        class_checks=[]
        for label,f in z["folds"].items():
            freq=f["meta"]["test_class_frequency"]
            prim=[float(freq[i]) for i in (0,1,2)]
            ok=(all(v>=tgate["min_test_frequency_each_primary_class"] for v in prim)
                and max(prim)<=tgate["max_test_frequency_any_primary_class"])
            class_checks.append({"fold":label,"frequency":freq,"ok":ok})
            target_ok &= ok
        eligible={}
        for name in hgate["eligible_models"]:
            m=z["summary"].get(name)
            if not m: continue
            need_ci=math.ceil(hgate["min_positive_block_ci_fraction"]*m["folds"])
            ok=(
              m["folds"]>=hgate["min_folds"] and
              (not hgate["require_wins_vs_vol90d_all_folds"] or m["wins_vs_vol90d"]==m["folds"]) and
              m["positive_ci_folds"]>=need_ci and
              m["mean_brier_gain_vs_vol90d"]>=hgate["min_mean_brier_gain_vs_vol90d"] and
              (not hgate["require_mean_log_loss_better_than_vol90d"] or m["mean_log_loss"]<base["mean_log_loss"])
            )
            eligible[name]={"ok":ok,"summary":m,"required_positive_ci_folds":need_ci}
        winners=[(v["summary"]["mean_brier"],k) for k,v in eligible.items() if v["ok"]]
        winners.sort()
        selected=winners[0][1] if winners and target_ok else None
        core[head]={"target_ok":target_ok,"target_distance_ratio_quantiles":q,
                    "class_checks":class_checks,"eligible":eligible,"selected":selected}
        all_core &= selected is not None

    blocks={
      "macro_daily_market":bool(macro["macro_market_gbdt_summary"]["research_gate_pass"]),
      "funding_oi":bool(deriv["summary"]["research_gate_pass"]),
      "breakout_memory":{h:bool(memory["heads"][h]["summary"]["research_gate_pass"]) for h in ("1h","4h","24h")},
    }
    result={
      "schema":"btc-predictive-vnext4r6-research-gate-result-v1",
      "status":"READY_FOR_FREEZE_RESEARCH_CANDIDATE" if all_core else "RESEARCH_REWORK",
      "trading_authority":False,
      "prospective_admission":False,
      "policy":policy,
      "core":core,
      "additional_blocks":blocks,
      "accepted_optional_blocks":[
        k for k,v in blocks.items() if (v is True)
      ],
      "rejected_optional_blocks":[
        k for k,v in blocks.items() if (v is False)
      ],
      "note":"Historical research gate authorizes only artifact freeze/testing, never production or trading."
    }
    (D/"research_gate_result.json").write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
    print(json.dumps(result,indent=2,sort_keys=True))

if __name__=="__main__":
    main()
