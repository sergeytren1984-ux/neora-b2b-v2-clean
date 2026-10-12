"""Negative tests: weekly resets must not inflate independent event counts."""
from btc_skill_rebuild.research_global_event_dedup_v7r6 import (
    global_event_summary,grouped_episodes)

H=4*60*60*1000
W=7*24*60*60*1000
M=60*1000

def test():
    # Same-side touches five minutes either side of a week boundary.
    a=global_event_summary([[(W-5*M,0)],[(W+5*M,0)]],H)
    assert a["globally_horizon_clustered_directional_episodes"]==1
    assert a["excess_weekly_episodes_due_to_boundary_splits"]==1
    # The exact same future first touch belongs to two forecast weeks.
    b=global_event_summary([[(W+5*M,0)],[(W+5*M,0)]],H)
    assert b["globally_unique_first_touch_timestamp_directions"]==1
    assert b["duplicate_first_touches_across_weeks"]==1
    # Opposite-side episodes never merge.
    c=global_event_summary([[(W-5*M,0)],[(W+5*M,1)]],H)
    assert c["globally_horizon_clustered_directional_episodes"]==2
    # Separated same-side impulses are distinct.
    d=global_event_summary([[(W-6*H,0)],[(W+6*H,0)]],H)
    assert d["globally_horizon_clustered_directional_episodes"]==2
    # Duplicates within a fold must not inflate global or weekly counts.
    e=global_event_summary([[(W,0),(W,0)],[]],H)
    assert e["globally_horizon_clustered_directional_episodes"]==1
    assert e["duplicate_first_touches_across_weeks"]==0
    # Exact horizon boundary is merged; horizon+1 is separate.
    assert len(grouped_episodes([(W,0),(W+H,0)],H))==1
    assert len(grouped_episodes([(W,0),(W+H+1,0)],H))==2
    # A chain of touches can span > horizon overall (same original rule).
    assert len(grouped_episodes([(W,0),(W+H,0),(W+2*H,0)],H))==1
    # No silent acceptance of bad side, negative time, or zero horizon.
    for events,h in [([[(W,2)]],H),([[(W,0)]],0),
                     ([[(W,-1)]],H),([[(-1,0)]],H)]:
        try:global_event_summary(events,h)
        except ValueError:pass
        else:raise AssertionError("invalid first-touch event accepted")
    print("GLOBAL_EVENT_DEDUP_NEGATIVE_TESTS_PASS")

if __name__=="__main__":test()
