"""Synthetic integration test of cross-week first-touch de-duplication."""
import datetime as dt
from unittest.mock import patch
from btc_skill_rebuild import research_episode_effective_sample_v7r6 as sample

UTC=dt.timezone.utc
START=dt.datetime(2026,1,1,tzinfo=UTC)
BORDER=START+dt.timedelta(days=7)
STEP=300000

def test():
    start_ms=int((START-dt.timedelta(days=2)).timestamp()*1000)
    rows=[[start_ms+i*STEP] for i in range(16*288)]
    target_ms=int((BORDER+dt.timedelta(minutes=15)).timestamp()*1000)
    target=(target_ms-start_ms)//STEP
    trigger={int((BORDER-dt.timedelta(minutes=15)).timestamp()*1000),
             int(BORDER.timestamp()*1000)}
    def label(rows,i,n,barrier):
        at=rows[i][0]+STEP
        if at in trigger:
            assert 0<target-i<=48
            return 0,target
        return 2,i
    with patch.object(sample,"FOLDS",(START,BORDER)),patch.object(
        sample,"HORIZONS",{"4h":(48,.012)}),patch.object(sample,"labels",label):
        r=sample.tally(rows)["horizons"]["4h"]
        assert r["total_directional_window_labels"]==2
        assert r["sum_weekly_conservative_event_episodes"]==2
        assert r["global_independent_directional_episodes"]==1
        assert r["global_unique_first_touch_timestamp_directions"]==1
        assert r["global_first_touch_and_episode_dedup"]["duplicate_first_touches_across_weeks"]==1
        rows[200][0]+=STEP
        try:sample.tally(rows)
        except ValueError:pass
        else:raise AssertionError("5m historical gap accepted")
    print("GLOBAL_FOLD_TALLY_INTEGRATION_PASS")
if __name__=="__main__":test()
