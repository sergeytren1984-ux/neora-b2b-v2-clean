from __future__ import annotations
from datetime import datetime,timedelta

def build_barrier_spec(reference,atr_pct,anchor,protocol):
    specs=[]
    for mult in protocol["barrier_policy"]["barriers_atr"]:
        delta=float(reference)*float(atr_pct)/100.0*float(mult)
        for hours in protocol["barrier_policy"]["horizons_hours"]:
            specs.append({
              "id":f"atr{mult:g}_{hours}h",
              "lower_price":float(reference)-delta,
              "upper_price":float(reference)+delta,
              "deadline_utc":(anchor+timedelta(hours=int(hours))).isoformat(),
              "probabilities":None,
              "probability_status":"WITHHELD_UNTIL_CALIBRATED"
            })
    return specs

def resolve_barrier(spec,hourly_candles,anchor):
    deadline=datetime.fromisoformat(spec["deadline_utc"])
    relevant=[c for c in hourly_candles if anchor < datetime.fromisoformat(c["close_time"]) <= deadline]
    for c in relevant:
        lo=float(c["low"])<=float(spec["lower_price"])
        hi=float(c["high"])>=float(spec["upper_price"])
        if lo and hi:
            return {"class":"BOTH_SAME_BAR","first_touch_time_utc":c["close_time"]}
        if lo:
            return {"class":"LOWER_FIRST","first_touch_time_utc":c["close_time"]}
        if hi:
            return {"class":"UPPER_FIRST","first_touch_time_utc":c["close_time"]}
    if relevant and datetime.fromisoformat(relevant[-1]["close_time"])>=deadline:
        return {"class":"NEITHER","first_touch_time_utc":None}
    return None
