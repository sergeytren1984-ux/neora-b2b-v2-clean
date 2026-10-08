"""Executable prospective scorer for frozen vNext5 first-passage.

No model training occurs here.  It evaluates canonical +/-1 sigma prospective
rows under the exact baseline, metric, due-grid, calibration and CI semantics
declared in evaluation_supplement.json.
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone, timedelta
from pathlib import Path

import numpy as np

HERE=Path(__file__).resolve().parent
SUPPLEMENT=json.loads((HERE/"evaluation_supplement.json").read_text())
EPS=1e-12


def parse_utc(value):
    dt=datetime.fromisoformat(str(value).replace("Z","+00:00"))
    if dt.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware UTC")
    dt=dt.astimezone(timezone.utc)
    return dt


def probability(raw):
    p=np.asarray(raw,dtype=float)
    if p.shape!=(4,) or not np.all(np.isfinite(p)) or np.any(p<0):
        raise ValueError("invalid raw probability")
    total=float(p.sum())
    if abs(total-1.0)>1e-8:
        raise ValueError("raw probability must sum to one")
    return p/total


def brier_losses(p,y):
    one=np.eye(4,dtype=float)[np.asarray(y,dtype=int)]
    return np.sum((np.asarray(p)-one)**2,axis=1)


def log_losses(p,y):
    p=np.asarray(p,dtype=float); y=np.asarray(y,dtype=int)
    return -np.log(np.clip(p[np.arange(len(y)),y],1e-12,1.0))


def ece10(p,y):
    p=np.asarray(p,dtype=float);y=np.asarray(y,dtype=int)
    conf=p.max(axis=1)
    correct=(p.argmax(axis=1)==y)
    out=0.0
    for i in range(10):
        lo=i/10.0; hi=(i+1)/10.0
        if i==9:
            m=(conf>=lo)&(conf<=1.0)
        else:
            m=(conf>=lo)&(conf<hi)
        if np.any(m):
            out += float(np.mean(m))*abs(
                float(np.mean(correct[m]))-float(np.mean(conf[m]))
            )
    return float(out)


def iso_week_key(dt):
    monday=(dt.date()-timedelta(days=dt.weekday()))
    return monday.isoformat()


def block_ci_gain(gain,anchors,resamples=2000,seed=20261008):
    gain=np.asarray(gain,dtype=float)
    keys=np.asarray([iso_week_key(x) for x in anchors],dtype=object)
    unique=list(dict.fromkeys(keys.tolist()))
    if len(unique)<4:
        return [None,None]
    blocks=[np.flatnonzero(keys==u) for u in unique]
    rng=np.random.default_rng(seed)
    vals=[]
    for _ in range(int(resamples)):
        pick=rng.integers(0,len(blocks),size=len(blocks))
        ids=np.concatenate([blocks[j] for j in pick])
        vals.append(float(np.mean(gain[ids])))
    return [float(x) for x in np.quantile(vals,[0.025,0.975])]


def vol_bin(value,edges):
    return int(np.digitize([float(value)],np.asarray(edges,dtype=float),right=True)[0])


def smoothed(counts,alpha=0.5):
    c=np.asarray(counts,dtype=float)+float(alpha)
    return c/c.sum()


def expected_candidates(head):
    return list(SUPPLEMENT["candidates"][head])


def validate_anchor(head,anchor):
    a=anchor.astimezone(timezone.utc)
    if a.second or a.microsecond or a.minute!=0:
        raise ValueError("anchor is off frozen UTC grid")
    if head=="4h" and a.hour not in (0,4,8,12,16,20):
        raise ValueError("4h anchor is off frozen UTC grid")
    if head=="24h" and a.hour!=0:
        raise ValueError("24h anchor is off frozen UTC grid")


def expected_anchor_grid(head,start,cutoff):
    cfg=SUPPLEMENT["anchor_grid"][head]
    horizon=timedelta(minutes=int(cfg["horizon_minutes"]))
    step=timedelta(minutes=int(cfg["cadence_minutes"]))
    cur=start.astimezone(timezone.utc)
    validate_anchor(head,cur)
    out=[]
    while cur+horizon<=cutoff:
        validate_anchor(head,cur)
        out.append(cur)
        cur += step
    return out


def validate_rows(rows,head,start,cutoff):
    horizon=timedelta(
        minutes=int(SUPPLEMENT["anchor_grid"][head]["horizon_minutes"])
    )
    deadline=timedelta(
        minutes=int(SUPPLEMENT["anchor_grid"][head]["forecast_deadline_minutes"])
    )
    candidates=expected_candidates(head)
    by={}
    for row in rows:
        if row.get("head")!=head or row.get("candidate_id") not in candidates:
            continue
        a=parse_utc(row["anchor_utc"])
        validate_anchor(head,a)
        if not (start<=a and a+horizon<=cutoff):
            continue
        key=(row["candidate_id"],a)
        if key in by:
            raise ValueError("duplicate prospective row")
        due=parse_utc(row["due_utc"])
        if due!=a+horizon:
            raise ValueError("due_utc mismatch")
        issued=parse_utc(row["forecast_issued_at_utc"])
        if issued>a+deadline:
            raise ValueError("late forecast")
        recorded=parse_utc(row["outcome_recorded_at_utc"])
        if recorded<due:
            raise ValueError("outcome recorded before due")
        y=int(row["outcome_class"])
        if y<0 or y>3:
            raise ValueError("invalid outcome class")
        p=probability(row["prediction_raw"])
        vol=float(row["volatility"])
        if not math.isfinite(vol) or vol<=0:
            raise ValueError("invalid volatility")
        by[key]={
            **row,
            "_anchor":a,
            "_due":due,
            "_p":p,
            "_y":y,
            "_vol":vol,
        }

    grid=expected_anchor_grid(head,start,cutoff)
    missing=[]
    for a in grid:
        for candidate in candidates:
            if (candidate,a) not in by:
                missing.append((candidate,a.isoformat()))
    if missing:
        raise ValueError("incomplete due grid: "+json.dumps(missing[:10]))
    return by,grid


def canonical_outcome_rows(by,grid,head):
    primary=expected_candidates(head)[0]
    rows=[by[(primary,a)] for a in grid]
    if head=="24h":
        other=expected_candidates(head)[1]
        for a,r in zip(grid,rows):
            q=by[(other,a)]
            if q["_y"]!=r["_y"] or abs(q["_vol"]-r["_vol"])>1e-15:
                raise ValueError("24h challenger outcome/volatility mismatch")
    return rows


def baseline_probabilities(outcome_rows,runtime_head):
    edges=runtime_head["volatility_bin_edges"]
    frozen_bins=runtime_head["frozen_prior_counts_by_bin"]
    frozen_global=runtime_head["frozen_global_prior_counts"]
    out=[]
    for i,row in enumerate(outcome_rows):
        a=row["_anchor"]; b=vol_bin(row["_vol"],edges)
        causal=[
            x for x in outcome_rows[:i]
            if x["_due"]<a and x["_anchor"]>=a-timedelta(days=90)
        ]
        same=[x for x in causal if vol_bin(x["_vol"],edges)==b]
        if len(same)>=30:
            counts=np.bincount([x["_y"] for x in same],minlength=4)
        elif len(causal)>=30:
            counts=np.bincount([x["_y"] for x in causal],minlength=4)
        else:
            counts=np.asarray(frozen_bins[str(b)],dtype=float)
            if counts.sum()<=0:
                counts=np.asarray(frozen_global,dtype=float)
        out.append(smoothed(counts,0.5))
    return np.vstack(out)


def score_candidate(candidate_rows,baseline,anchors,y):
    p=np.vstack([x["_p"] for x in candidate_rows])
    bl=brier_losses(baseline,y)
    cl=brier_losses(p,y)
    llb=log_losses(baseline,y); llc=log_losses(p,y)
    gain=bl-cl
    ci=block_ci_gain(
        gain,anchors,
        SUPPLEMENT["confidence_interval"]["bootstrap_resamples"],
        SUPPLEMENT["confidence_interval"]["seed"],
    )
    e=ece10(p,y); be=ece10(baseline,y)
    out={
        "n":len(y),
        "brier":float(np.mean(cl)),
        "baseline_brier":float(np.mean(bl)),
        "brier_gain":float(np.mean(gain)),
        "brier_gain_ci95":ci,
        "log_loss":float(np.mean(llc)),
        "baseline_log_loss":float(np.mean(llb)),
        "logloss_gain":float(np.mean(llb-llc)),
        "ece10":e,
        "baseline_ece10":be,
    }
    out["gate_pass"]=bool(
        out["brier_gain"]>0
        and ci[0] is not None and ci[0]>0
        and out["logloss_gain"]>0
        and e<=SUPPLEMENT["gates"]["calibration_max_ece10"]
        and e<=be+SUPPLEMENT["gates"]["calibration_max_ece10_degradation_vs_baseline"]
    )
    return out,p,cl


def paired_advantage_ci(loss_a,loss_b,anchors):
    # positive means candidate A has lower Brier loss than B
    gain=np.asarray(loss_b)-np.asarray(loss_a)
    return block_ci_gain(
        gain,anchors,
        SUPPLEMENT["confidence_interval"]["bootstrap_resamples"],
        SUPPLEMENT["confidence_interval"]["seed"],
    )


def score(rows,head,start_utc,cutoff_utc,runtime):
    start=parse_utc(start_utc); cutoff=parse_utc(cutoff_utc)
    by,grid=validate_rows(rows,head,start,cutoff)
    outcome=canonical_outcome_rows(by,grid,head)
    anchors=[x["_anchor"] for x in outcome]
    y=np.asarray([x["_y"] for x in outcome],dtype=int)
    baseline=baseline_probabilities(outcome,runtime["heads"][head])

    minimum=SUPPLEMENT["decision_minima"][head]
    calendar_days=(cutoff-start).total_seconds()/86400.0
    minima_met=(
        calendar_days>=float(minimum["calendar_days"])
        and len(grid)>=int(minimum["fixed_phase_nonoverlap_windows"])
    )

    candidate_results={}
    losses={}
    for candidate in expected_candidates(head):
        cr=[by[(candidate,a)] for a in grid]
        result,p,loss=score_candidate(cr,baseline,anchors,y)
        candidate_results[candidate]=result
        losses[candidate]=loss

    decision={
        "head":head,
        "start_utc":start.isoformat(),
        "cutoff_utc":cutoff.isoformat(),
        "expected_due_windows":len(grid),
        "calendar_days":calendar_days,
        "decision_minima_met":bool(minima_met),
        "candidates":candidate_results,
        "prospective_skill_proven":False,
        "trading_authority":False,
    }

    if head!="24h":
        c=expected_candidates(head)[0]
        decision["admission_ready"]=bool(minima_met and candidate_results[c]["gate_pass"])
        decision["selected_candidate"]=c if decision["admission_ready"] else None
    else:
        a,b=expected_candidates(head)
        pa=candidate_results[a]["gate_pass"]
        pb=candidate_results[b]["gate_pass"]
        selected=None; status="NO_WINNER_REWORK"
        comparison=None
        if minima_met:
            if pa and not pb:
                selected=a; status="WINNER_SELECTED"
            elif pb and not pa:
                selected=b; status="WINNER_SELECTED"
            elif pa and pb:
                ci_ab=paired_advantage_ci(losses[a],losses[b],anchors)
                ci_ba=[-ci_ab[1],-ci_ab[0]] if ci_ab[0] is not None else [None,None]
                comparison={"a_over_b_ci95":ci_ab,"b_over_a_ci95":ci_ba}
                if ci_ab[0] is not None and ci_ab[0]>0:
                    selected=a; status="WINNER_SELECTED"
                elif ci_ba[0] is not None and ci_ba[0]>0:
                    selected=b; status="WINNER_SELECTED"
                else:
                    status="NO_WINNER_CONTINUE_PROSPECTIVE"
        decision["challenger_comparison"]=comparison
        decision["selected_candidate"]=selected
        decision["admission_ready"]=bool(selected is not None)
        decision["winner_status"]=status

    return decision


def load_rows(path):
    rows=[]
    for line in Path(path).read_text().splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument("--events-jsonl",required=True)
    p.add_argument("--head",required=True,choices=("1h","4h","24h"))
    p.add_argument("--start-utc",required=True)
    p.add_argument("--cutoff-utc",required=True)
    p.add_argument(
        "--runtime",
        default=str(HERE/"build/evaluation_runtime.json"),
    )
    args=p.parse_args(argv)
    runtime=json.loads(Path(args.runtime).read_text())
    result=score(
        load_rows(args.events_jsonl),
        args.head,args.start_utc,args.cutoff_utc,runtime,
    )
    print(json.dumps(result,indent=2,sort_keys=True))


if __name__=="__main__":
    main()
