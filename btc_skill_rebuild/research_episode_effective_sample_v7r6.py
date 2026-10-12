"""Historical 5m first-touch effective sample, with global fold dedup."""
import datetime as dt,gzip,json,pathlib,hashlib,argparse
from btc_skill_rebuild.research_execution_drift_v7r6 import STEP
from btc_skill_rebuild.research_competing_barriers_v7r6 import labels,HORIZONS
from btc_skill_rebuild.research_walkforward_barriers_v7r6 import FOLDS,UTC
from btc_skill_rebuild.research_global_event_dedup_v7r6 import grouped_episodes,global_event_summary

def tally(rows):
    if not rows:raise ValueError("empty 5m history")
    for a,b in zip(rows,rows[1:]):
        if int(b[0])-int(a[0])!=STEP:raise ValueError("5m gap")
    result={}
    for h,(n,barrier) in HORIZONS.items():
        slices=[];weekly_events=[]
        for start in FOLDS:
            begin=int(start.timestamp()*1000);end=begin+7*86400000
            touches=[];predictive_slots=none=ambiguous=directional=0
            for i in range(289,len(rows)-n):
                at=int(rows[i][0])+STEP
                if at%(15*60000) or at<begin or at>=end:continue
                label,idx=labels(rows,i,n,barrier)
                predictive_slots+=1
                if label in (0,1):
                    directional+=1
                    touches.append((int(rows[idx][0]),label))
                elif label==2:none+=1
                else:ambiguous+=1
            unique=set(touches);weekly_events.append(unique)
            episodes=grouped_episodes(unique,n*STEP)
            slices.append({
                "test_week_utc":start.date().isoformat(),
                "full_due_15m_slots":predictive_slots,
                "directionally_resolved_slot_labels":directional,
                "distinct_exact_minute_directional_first_touches":len(unique),
                "conservative_nonoverlapping_directional_episodes":len(episodes),
                "no_barrier_labels":none,
                "ambiguous_same_5m_bar_labels":ambiguous,
                "unique_UP_episodes":sum(c["side"]==0 for c in episodes),
                "unique_DOWN_episodes":sum(c["side"]==1 for c in episodes),
                "window_count_overstates_episode_count_ratio":directional/max(1,len(episodes))
            })
        global_counts=global_event_summary(weekly_events,n*STEP)
        result[h]={
            "weekly":slices,
            "n_independent_calendar_day_blocks":28,
            "total_15m_windows":sum(x["full_due_15m_slots"] for x in slices),
            "total_directional_window_labels":sum(x["directionally_resolved_slot_labels"] for x in slices),
            "total_unique_first_touch_timestamp_directions":sum(x["distinct_exact_minute_directional_first_touches"] for x in slices),
            "sum_weekly_conservative_event_episodes":sum(x["conservative_nonoverlapping_directional_episodes"] for x in slices),
            "global_first_touch_and_episode_dedup":global_counts,
            "global_unique_first_touch_timestamp_directions":global_counts["globally_unique_first_touch_timestamp_directions"],
            "global_independent_directional_episodes":global_counts["globally_horizon_clustered_directional_episodes"],
            "weekly_sums_not_globally_independent":True
        }
    return {"schema":"btc-v7r6-event-episode-effective-sample-v2",
            "only_historical_already_seen":True,"trading_authority":False,
            "first_touch_5m_candle_ambiguity_preserved":True,
            "forecast_windows_are_not_independent_events":True,"horizons":result}

def run(raw,out):
    with gzip.open(raw,"rt") as f:rows=json.load(f)
    result=tally(rows)
    result["raw_gzip_sha256"]=hashlib.sha256(pathlib.Path(raw).read_bytes()).hexdigest()
    pathlib.Path(out).write_text(json.dumps(result,indent=2,sort_keys=True,allow_nan=False)+"\n")
    for h,v in result["horizons"].items():
        print("EFFECTIVE_EVENT_SAMPLE",h,"weekly_episodes",
              v["sum_weekly_conservative_event_episodes"],
              "global_episodes",v["global_independent_directional_episodes"],flush=True)
    return result
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--raw",required=True);p.add_argument("--out",required=True)
    x=p.parse_args();run(x.raw,x.out)
