"""Regression tests for defects found by the independent vNext3 audit."""
from __future__ import annotations

import unittest
import sys
from pathlib import Path
from datetime import datetime,timedelta,timezone

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))

from predictive_vnext4.scorecard import score

UTC=timezone.utc


def d(p):
    return {"lower_first":p[0],"upper_first":p[1],"neither":p[2],"ambiguous_same_bar":p[3]}


class AdmissionRegressionTests(unittest.TestCase):
    def test_overlapping_wins_cannot_override_nonoverlap_losses(self):
        # 92 days hourly = 2208 overlapping forecasts. Every fixed 72h phase
        # anchor is made intentionally bad for the candidate; all other anchors
        # are made excellent. vNext3 could admit this construction because its
        # performance metrics were computed on all overlapping forecasts.
        start=datetime(2026,10,5,tzinfo=UTC)
        events=[]
        for i in range(92*24):
            a=start+timedelta(hours=i);slot=a.strftime("%Y%m%dT%H%M%SZ")
            actual=i%3  # exercise several classes
            base=[.20,.20,.60,0.0] if actual!=3 else [.2,.2,.59,.01]
            if i%72==0:
                # Candidate loses badly on every independent fixed-phase window.
                pred=[.90,.05,.05,0.0]
                if actual==0: pred=[.05,.90,.05,0.0]
            else:
                pred=[.02,.02,.94,.02]
                pred=[.02,.02,.02,.02]
                pred[actual]=.94
            control={
                "primary_distribution":d(base),
                "secondary_distribution":d(base),
                "volatility_bin":(i//72)%3,
            }
            contender={m:{"class_distribution":d(pred),
                          "alerts_at_calibration_fpr20":{"lower_first":False,"upper_first":False,
                                                         "lower_threshold":.5,"upper_threshold":.5}}
                       for m in ("logistic","gbdt","competing_risks")}
            events.append({"type":"FORECAST_ISSUED","slot":slot,"anchor_utc":a.isoformat(),
                           "due_utc":(a+timedelta(hours=72)).isoformat(),
                           "control":control,"contenders":contender})
            cls=("LOWER_FIRST","UPPER_FIRST","NEITHER","AMBIGUOUS_SAME_BAR")[actual]
            events.append({"type":"OUTCOME_RECORDED","slot":slot,"outcome_class":cls,
                           "first_touch_time_utc":(a+timedelta(hours=1)).isoformat()})
        result=score(events,"hourly",72,90,30,12)
        self.assertGreaterEqual(result["fixed_phase_nonoverlap_count"],30)
        self.assertFalse(result["admission_ready"])
        for m in ("logistic","gbdt","competing_risks"):
            self.assertFalse(result["contenders"][m]["passes_all"])
            self.assertGreater(result["contenders"][m]["nonoverlap"]["brier"],
                               result["primary_baseline_nonoverlap"]["brier"])

    def test_episode_gate_uses_independent_windows(self):
        start=datetime(2026,10,5,tzinfo=UTC);events=[]
        for i in range(100*24):
            a=start+timedelta(hours=i);slot=a.strftime("%Y%m%dT%H%M%SZ")
            # Bin changes rapidly on overlapping anchors but fixed-phase 72h
            # anchors remain bin 0, so independent episode coverage must fail.
            b=0 if i%72==0 else (i%3)
            base=d([.25,.25,.49,.01]);pred=d([.25,.25,.49,.01])
            c={"primary_distribution":base,"secondary_distribution":base,"volatility_bin":b}
            cc={m:{"class_distribution":pred,
                   "alerts_at_calibration_fpr20":{"lower_first":False,"upper_first":False,
                                                  "lower_threshold":.5,"upper_threshold":.5}}
                for m in ("logistic","gbdt","competing_risks")}
            events.append({"type":"FORECAST_ISSUED","slot":slot,"anchor_utc":a.isoformat(),
                           "due_utc":(a+timedelta(hours=72)).isoformat(),"control":c,"contenders":cc})
            events.append({"type":"OUTCOME_RECORDED","slot":slot,"outcome_class":"NEITHER",
                           "first_touch_time_utc":None})
        result=score(events,"hourly",72,90,30,12)
        self.assertEqual(result["volatility_bins_seen_nonoverlap"],[0])
        self.assertEqual(result["independent_volatility_episode_count"],1)
        self.assertFalse(result["admission_ready"])


if __name__=="__main__":
    unittest.main()
