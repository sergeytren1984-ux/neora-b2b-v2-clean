"""BTC v7R6 research: horizon-anchored versus single-link episode counts.

Pure mathematics; no new trading signal or production model.
Do not call first-touch labels independent just because 15m issue slots differ.
Do not treat same-side single-link clusters as bounded horizon episodes:
a chain can extend indefinitely beyond one horizon. This module reports
three transparent sensitivity counts on IDENTICAL global event labels:
(1) original same-side chained (historical lower-count diagnostic),
(2) same-side fixed-first-touch horizon-anchored,
(3) across-side fixed-first-touch horizon-anchored nonoverlap.

All three are retrospective DESCRIPTIVE event-dependence diagnostics;
none prove independent stochastic price innovations or prospective skill.
"""
from __future__ import annotations
import argparse,datetime as dt,gzip,hashlib,json,pathlib
from btc_skill_rebuild.research_execution_drift_v7r6 import STEP
from btc_skill_rebuild.research_competing_barriers_v7r6 import HORIZONS,labels
from btc_skill_rebuild.research_walkforward_barriers_v7r6 import FOLDS
from btc_skill_rebuild.research_global_event_dedup_v7r6 import grouped_episodes

def checked_events(events):
    result=set()
    for t,side in events:
        if not isinstance(t,int) or isinstance(t,bool) or t<0:
            raise ValueError("invalid first-touch UTC milliseconds")
        if type(side) is not int or side not in (0,1):
            raise ValueError("invalid first-touch side")
        result.add((t,side))
    return sorted(result)

def anchored(events,horizon_ms,*,split_sides):
    """Decluster by FIRST touch; never chain by last touch.

    split_sides=False: an UP/DOWN reversal inside one anchored horizon is
    one mixed-direction price episode, not two independent events.
    """
    if type(horizon_ms) is not int or horizon_ms<=0:
        raise ValueError("invalid fixed event horizon")
    ordered=checked_events(events)
    groups=[]
    latest={}
    for t,side in ordered:
        key=side if split_sides else "ALL"
        cluster=latest.get(key)
        if cluster is None or t-cluster["first_touch_ms"]>horizon_ms:
            cluster={"first_touch_ms":t,"last_touch_ms":t,
                     "UP_touches":0,"DOWN_touches":0,
                     "distinct_first_touch_pairs":0}
            groups.append(cluster)
            latest[key]=cluster
        cluster["last_touch_ms"]=t
        cluster["distinct_first_touch_pairs"]+=1
        cluster["UP_touches"]+=int(side==0)
        cluster["DOWN_touches"]+=int(side==1)
    assert sum(c["distinct_first_touch_pairs"] for c in groups)==len(ordered)
    assert all(c["last_touch_ms"]-c["first_touch_ms"]<=horizon_ms for c in groups)
    return groups

def summarize(events,horizon_ms):
    events=checked_events(events)
    original=grouped_episodes(events,horizon_ms)
    side_anchor=anchored(events,horizon_ms,split_sides=True)
    all_anchor=anchored(events,horizon_ms,split_sides=False)
    overspan=[c for c in original if
              c["last_touch_ms"]-c["first_touch_ms"]>horizon_ms]
    return {
        "global_unique_first_touch_time_direction_pairs":len(events),
        "original_same_side_single_link_chained_episodes":len(original),
        "original_chains_spanning_more_than_one_horizon":len(overspan),
        "original_longest_single_link_chain_minutes":(
            max((c["last_touch_ms"]-c["first_touch_ms"] for c in original),
                default=0)/60000),
        "same_side_first_touch_anchored_episodes":len(side_anchor),
        "both_sides_first_touch_anchored_nonoverlapping_windows":len(all_anchor),
        "both_sides_anchored_windows_containing_UP_and_DOWN":sum(
            bool(c["UP_touches"] and c["DOWN_touches"]) for c in all_anchor),
        "anchor_episode_window_ms":horizon_ms,
        "no_event_treated_as_independent_merely_by_separate_forecast_slot":True,
        "anchored_counts_are_not_proof_of_stochastic_independence":True,
        "retrospective_labels_already_seen":True,
        "trading_authority":False,
    }

def evaluate(rows):
    if not rows or len(rows)<300:
        raise ValueError("missing 5m historical candles")
    for first,second in zip(rows,rows[1:]):
        if int(second[0])-int(first[0])!=STEP:
            raise ValueError("historical 5m time grid is incomplete")
    out={}
    for horizon,(bars,barrier) in HORIZONS.items():
        event_pairs=set()
        due=0
        directional_due=0
        for fold in FOLDS:
            begin=int(fold.timestamp()*1000)
            end=begin+7*86400000
            for i in range(289,len(rows)-bars):
                issue=int(rows[i][0])+STEP
                if issue%(15*60000) or issue<begin or issue>=end:
                    continue
                due+=1
                label,touch=labels(rows,i,bars,barrier)
                if label in (0,1):
                    directional_due+=1
                    event_pairs.add((int(rows[touch][0]),label))
        out[horizon]={
            "all_predefined_historical_15min_due":due,
            "directional_labels_in_overlapping_due":directional_due,
            **summarize(event_pairs,bars*STEP)}
    return {
        "schema":"btc-v7r6-event-dependence-anchor-sensitivity-v1",
        "horizons":out,
        "same_historical_5m_labels_as_original_v7r6":True,
        "research_only_no_new_signal":True,
        "not_new_prospective_observations":True,
        "trading_authority":False,
    }

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--raw",required=True)
    p.add_argument("--out",required=True)
    args=p.parse_args()
    with gzip.open(args.raw,"rt") as fh:
        rows=json.load(fh)
    output=evaluate(rows)
    output["source_gzip_sha256"]=hashlib.sha256(pathlib.Path(args.raw).read_bytes()).hexdigest()
    pathlib.Path(args.out).write_text(json.dumps(output,indent=2,sort_keys=True)+"\n")
    for h,summary in output["horizons"].items():
        print("BTC_V7R6_EVENT_DEPENDENCE",h,
              "unique",summary["global_unique_first_touch_time_direction_pairs"],
              "single_link",summary["original_same_side_single_link_chained_episodes"],
              "anchored_same_side",summary["same_side_first_touch_anchored_episodes"],
              "anchored_both_sides",summary["both_sides_first_touch_anchored_nonoverlapping_windows"],
              "long_chains",summary["original_chains_spanning_more_than_one_horizon"],
              flush=True)

if __name__=="__main__":main()
