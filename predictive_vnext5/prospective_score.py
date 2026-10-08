"""Authoritative prospective scorer for frozen vNext5 first-passage R2.

The numerical model is unchanged.  This module closes evaluator-input findings:
- canonical primary rows only;
- forecast issuance must be at/after anchor and before the frozen deadline;
- outcome class is a strict integer enum (bool/fractional values rejected);
- outcome must be observable no later than the requested evaluation cutoff;
- runtime/supplement/protocol/scorer are hash-bound to the frozen manifest;
- custom-zone rows can never enter canonical primary admission.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime, timezone, timedelta
from pathlib import Path

import numpy as np

HERE=Path(__file__).resolve().parent
SUPPLEMENT_PATH=HERE/"evaluation_supplement.json"
PROTOCOL_PATH=HERE/"prospective_protocol.json"
RUNTIME_PATH=HERE/"frozen_evaluation_runtime.json"
SUPPLEMENT=json.loads(SUPPLEMENT_PATH.read_text())
EPS=1e-12

CANONICAL_SCHEMA=SUPPLEMENT["input_row_schema"]["schema"]
CANONICAL_QUERY_TYPE=SUPPLEMENT["input_row_schema"]["query_type"]
CANONICAL_TARGET_ID=SUPPLEMENT["input_row_schema"]["target_id"]
CANONICAL_LOWER_SIGMA=float(SUPPLEMENT["canonical_target"]["lower_sigma"])
CANONICAL_UPPER_SIGMA=float(SUPPLEMENT["canonical_target"]["upper_sigma"])
REQUIRED_KEYS=set(SUPPLEMENT["input_row_schema"]["required"])
ALLOWED_KEYS=set(SUPPLEMENT["input_row_schema"]["allowed"])


def file_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def parse_utc(value):
    if type(value) is not str:
        raise ValueError("timestamp must be an ISO-8601 string")
    dt=datetime.fromisoformat(value.replace("Z","+00:00"))
    if dt.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware UTC")
    return dt.astimezone(timezone.utc)


def _strict_number(value,name):
    if isinstance(value,bool) or not isinstance(value,(int,float,np.integer,np.floating)):
        raise ValueError(f"{name} must be numeric")
    out=float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} must be finite")
    return out


def probability(raw):
    if not isinstance(raw,(list,tuple)) or len(raw)!=4:
        raise ValueError("prediction_raw must be array[4]")
    vals=[]
    for x in raw:
        if isinstance(x,bool) or not isinstance(x,(int,float,np.integer,np.floating)):
            raise ValueError("prediction_raw contains non-numeric value")
        vals.append(float(x))
    p=np.asarray(vals,dtype=float)
    if not np.all(np.isfinite(p)) or np.any(p<0):
        raise ValueError("invalid raw probability")
    total=float(p.sum())
    if abs(total-1.0)>1e-8:
        raise ValueError("raw probability must sum to one")
    return p/total


def strict_outcome_class(value):
    if type(value) is not int:
        raise ValueError("outcome_class must be strict integer enum 0..3")
    if value<0 or value>3:
        raise ValueError("outcome_class must be strict integer enum 0..3")
    return value


def _canonical_sigma(value,expected,name):
    v=_strict_number(value,name)
    if not math.isclose(v,float(expected),rel_tol=0.0,abs_tol=1e-12):
        raise ValueError("non-canonical target is forbidden in primary admission")
    return v


def authoritative_runtime(runtime_override=None):
    """Load the sole frozen source-controlled baseline runtime.

    Cryptographic binding of these bytes to the exact source commit is enforced
    by prospective_admission -> verified_evidence.  Direct caller replacement is
    rejected here as an additional fail-closed guard.
    """
    runtime=json.loads(RUNTIME_PATH.read_text())
    if runtime_override is not None:
        if not isinstance(runtime_override,dict) or runtime_override!=runtime:
            raise ValueError("non-authoritative runtime rejected")
    return runtime

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


def validate_canonical_row_schema(row):
    if type(row) is not dict:
        raise ValueError("prospective row must be object")
    keys=set(row)
    missing=REQUIRED_KEYS-keys
    extra=keys-ALLOWED_KEYS
    if missing:
        raise ValueError("missing canonical row fields: "+",".join(sorted(missing)))
    if extra:
        raise ValueError("unexpected canonical row fields: "+",".join(sorted(extra)))
    if row["schema"]!=CANONICAL_SCHEMA:
        raise ValueError("canonical row schema mismatch")
    if row["query_type"]!=CANONICAL_QUERY_TYPE:
        raise ValueError("custom/non-canonical row forbidden in primary admission")
    if row["target_id"]!=CANONICAL_TARGET_ID:
        raise ValueError("canonical target id mismatch")
    _canonical_sigma(row["lower_sigma"],CANONICAL_LOWER_SIGMA,"lower_sigma")
    _canonical_sigma(row["upper_sigma"],CANONICAL_UPPER_SIGMA,"upper_sigma")


def validate_rows(rows,head,start,cutoff):
    horizon=timedelta(
        minutes=int(SUPPLEMENT["anchor_grid"][head]["horizon_minutes"])
    )
    deadline=timedelta(
        minutes=int(SUPPLEMENT["anchor_grid"][head]["forecast_deadline_minutes"])
    )
    candidates=expected_candidates(head)
    by={}
    seen_any=False
    for row in rows:
        if type(row) is not dict:
            raise ValueError("prospective row must be object")
        # Rows for other heads are ignored only after their schema is known.
        # This prevents malformed/custom rows from masquerading as harmless extras.
        if row.get("head")!=head:
            continue
        seen_any=True
        validate_canonical_row_schema(row)
        if row["candidate_id"] not in candidates:
            raise ValueError("candidate_id is not authorized for head")
        a=parse_utc(row["anchor_utc"])
        validate_anchor(head,a)
        if not (start<=a and a+horizon<=cutoff):
            raise ValueError("row anchor outside requested evaluation grid")
        key=(row["candidate_id"],a)
        if key in by:
            raise ValueError("duplicate prospective row")
        due=parse_utc(row["due_utc"])
        if due!=a+horizon:
            raise ValueError("due_utc mismatch")
        issued=parse_utc(row["forecast_issued_at_utc"])
        if issued<a:
            raise ValueError("forecast issued before anchor")
        if issued>a+deadline:
            raise ValueError("late forecast")
        recorded=parse_utc(row["outcome_recorded_at_utc"])
        if recorded<due:
            raise ValueError("outcome recorded before due")
        if recorded>cutoff:
            raise ValueError("outcome recorded after evaluation cutoff")
        y=strict_outcome_class(row["outcome_class"])
        p=probability(row["prediction_raw"])
        vol=_strict_number(row["volatility"],"volatility")
        if vol<=0:
            raise ValueError("invalid volatility")
        by[key]={
            **row,
            "_anchor":a,
            "_due":due,
            "_p":p,
            "_y":y,
            "_vol":vol,
        }

    if not seen_any:
        raise ValueError("no rows for requested head")
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
            if (
                q["outcome_recorded_at_utc"]!=r["outcome_recorded_at_utc"]
                or q["due_utc"]!=r["due_utc"]
                or q["target_id"]!=r["target_id"]
            ):
                raise ValueError("24h challenger canonical outcome authority mismatch")
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
    gain=np.asarray(loss_b)-np.asarray(loss_a)
    return block_ci_gain(
        gain,anchors,
        SUPPLEMENT["confidence_interval"]["bootstrap_resamples"],
        SUPPLEMENT["confidence_interval"]["seed"],
    )


def score(rows,head,start_utc,cutoff_utc,runtime=None):
    start=parse_utc(start_utc); cutoff=parse_utc(cutoff_utc)
    if cutoff<=start:
        raise ValueError("cutoff must be after start")
    runtime=authoritative_runtime(runtime)
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
        "target_id":CANONICAL_TARGET_ID,
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
    raise SystemExit(
        "standalone JSONL scoring is non-authoritative; "
        "use predictive_vnext5/prospective_admission.py"
    )


if __name__=="__main__":
    main()
