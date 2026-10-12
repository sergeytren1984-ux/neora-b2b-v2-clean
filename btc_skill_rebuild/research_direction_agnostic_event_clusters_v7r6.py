"""Mathematical sensitivity of first-touch effective sample to BOTH directions.

Research-only BTC v7R6 denominator audit; NOT a new forecaster or alarm.
The already-seen Binance 5m history is NEVER a prospective test.

One independent event is not each 15m slot. Even deduplication by
(touch_candle, side) can count nearby UP and DOWN moves as independent.
We therefore report an additional, MORE CONSERVATIVE, side-agnostic
connected-component denominator: sort unique first-touch timestamps
globally (not by week) and connect consecutive touches whose spacing
is <= the ORIGINAL horizon, irrespective of direction. No threshold
is selected from outcomes; the horizon is already fixed at 1h or 4h.

This is an episode-count sensitivity analysis, not a claim that
components are statistically independent (macro regimes can persist).
"""
from __future__ import annotations
import argparse,datetime as dt,gzip,hashlib,json,pathlib
from btc_skill_rebuild.research_competing_barriers_v7r6 import labels,HORIZONS
from btc_skill_rebuild.research_execution_drift_v7r6 import STEP
from btc_skill_rebuild.research_walkforward_barriers_v7r6 import FOLDS

DAY_MS=86400000
SLOT_MS=900000

def side_agnostic_clusters(touches,span_ms):
    """Deduplicate globally, then cluster consecutive timestamps, both sides.

    Event tuples: (UTC first-touch 5m candle opening ms, side=0/1).
    Duplicates are the same physical touch, not new independent trials.
    """
    if not isinstance(span_ms,int) or span_ms<=0:
        raise ValueError("horizon span must be positive integer ms")
    unique=set()
    for t,side in touches:
        if type(t) is not int or t<0 or type(side) is not int or side not in (0,1):
            raise ValueError("invalid UTC first touch or directional class")
        unique.add((t,side))
    ordered=sorted(unique)
    result=[]
    for touch,side in ordered:
        if not result or touch-result[-1]["last_touch_ms"]>span_ms:
            result.append({"first_touch_ms":touch,"last_touch_ms":touch,
                           "sides":[side],"unique_touch_labels":1})
        else:
            group=result[-1]
            group["last_touch_ms"]=touch
            group["unique_touch_labels"]+=1
            if side not in group["sides"]:
                group["sides"].append(side)
    return result

def score_history(rows):
    """Fixed four previously studied weeks; never tune or drop incomplete due."""
    if len(rows)<10000:
        raise ValueError("not the fixed 65-day research archive")
    opens=[int(row[0]) for row in rows]
    if any(b-a!=STEP for a,b in zip(opens,opens[1:])):
        raise ValueError("gap/duplicate in 5m research history")
    result={}
    for h,(n,barrier) in HORIZONS.items():
        all_touches=set()
        weekly=[]
        for fold in FOLDS:
            start=int(fold.timestamp()*1000)
            stop=start+7*DAY_MS
            due=0;directional=0;ambiguous=0;range_count=0
            events=set()
            for i in range(289,len(rows)-n):
                anchor=opens[i]+STEP
                if anchor%SLOT_MS or not start<=anchor<stop:
                    continue
                due+=1
                side,hit=labels(rows,i,n,barrier)
                if side in (0,1):
                    directional+=1
                    events.add((opens[hit],side))
                elif side==2:range_count+=1
                elif side==3:ambiguous+=1
                else:raise ValueError("unknown historical first-touch class")
            if due!=directional+range_count+ambiguous:
                raise ValueError("directional sample count does not reconcile")
            all_touches.update(events)
            weekly.append({"week_start_utc":fold.isoformat(),
                           "resolved_15m_due":due,
                           "directional_window_labels":directional,
                           "range_window_labels":range_count,
                           "ambiguous_window_labels":ambiguous,
                           "unique_touch_candle_and_side":len(events),
                           "side_agnostic_episode_count":len(
                               side_agnostic_clusters(events,n*STEP))})
        clusters=side_agnostic_clusters(all_touches,n*STEP)
        result[h]={
            "fixed_horizon_minutes":n*5,
            "full_registered_4week_due_15m":4*7*24*4,
            "historical_resolved_15m_due":sum(w["resolved_15m_due"] for w in weekly),
            "missing_or_immature_due_in_archive":4*7*24*4-sum(w["resolved_15m_due"] for w in weekly),
            "historical_directional_window_labels":sum(w["directional_window_labels"] for w in weekly),
            "global_unique_touch_candle_and_side":len(all_touches),
            "side_agnostic_global_clusters":len(clusters),
            "mixed_UP_DOWN_clusters":sum(len(c["sides"])==2 for c in clusters),
            "global_clustering_includes_week_boundaries":True,
            "opposite_side_touches_can_be_same_risk_episode":True,
            "all_15m_slots_not_independent":True,
            "weekly":weekly}
        if result[h]["missing_or_immature_due_in_archive"]<0:
            raise ValueError("more resolved due than preregistered")
    return {
        "schema":"btc-v7r6-historical-both-direction-effective-episode-audit-v1",
        "history_already_seen_not_prospective":True,
        "fixed_horizons_not_fit_on_test":True,
        "true_independence_not_established":True,
        "trading_authority":False,
        "horizons":result}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--raw",required=True)
    p.add_argument("--out",required=True)
    a=p.parse_args()
    source=pathlib.Path(a.raw)
    with gzip.open(source,"rt") as stream:rows=json.load(stream)
    report=score_history(rows)
    report["historic_raw_sha256"]=hashlib.sha256(source.read_bytes()).hexdigest()
    pathlib.Path(a.out).write_text(json.dumps(report,indent=2,sort_keys=True,allow_nan=False)+"\n")
    for h,x in report["horizons"].items():
        print("BOTH_DIRECTION_EVENT_COUNT",h,
              "unique_touches",x["global_unique_touch_candle_and_side"],
              "side_agnostic_clusters",x["side_agnostic_global_clusters"],
              "mixed_direction_clusters",x["mixed_UP_DOWN_clusters"],
              "unmatured_due",x["missing_or_immature_due_in_archive"])
if __name__=="__main__":main()
