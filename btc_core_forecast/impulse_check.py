"""Fresh price regime guard; detects observed movement, never claims prediction.

Addresses the failure where a stale forecast is described as current quiet
conditions while BTC has already moved rapidly. Original R6 is untouched.
"""
import datetime as dt
import math
from btc_demand_v7.live_snapshot import strict_closed

MOVE_6M_USDT=500.
MOVE_15M_USDT=1000.
MAX_AGE_SECONDS=120

def inspect(rows,anchor_ms,received_ms):
    rows=strict_closed(rows,60000,anchor_ms,16)
    if not 0<=received_ms-anchor_ms<=MAX_AGE_SECONDS*1000:raise ValueError('stale or future current market receipt')
    if len(rows)!=16:raise ValueError('exact 16 minute grid required')
    price=float(rows[-1][4]);d6=price-float(rows[-7][4]);d15=price-float(rows[0][4])
    if not all(math.isfinite(x) for x in (price,d6,d15)):raise ValueError('nonfinite minute movement')
    range6=max(float(r[2]) for r in rows[-6:])-min(float(r[3]) for r in rows[-6:])
    range15=max(float(r[2]) for r in rows[-15:])-min(float(r[3]) for r in rows[-15:])
    rapid=abs(d6)>=MOVE_6M_USDT or abs(d15)>=MOVE_15M_USDT or range6>=MOVE_6M_USDT or range15>=MOVE_15M_USDT
    if rapid:
        sign=d6 if abs(d6)>=MOVE_6M_USDT else (d15 if abs(d15)>=MOVE_15M_USDT else 0.)
        state=('БЫСТРЫЙ_РОСТ_УЖЕ_НАБЛЮДАЕТСЯ' if sign>0 else 'БЫСТРОЕ_СНИЖЕНИЕ_УЖЕ_НАБЛЮДАЕТСЯ') if sign else 'РЕЗКИЕ_КОЛЕБАНИЯ_УЖЕ_НАБЛЮДАЮТСЯ'
    else:state='ПОРОГИ_БЫСТРОГО_ДВИЖЕНИЯ_НЕ_ПЕРЕСЕЧЕНЫ'
    return {'schema':'btc-fresh-impulse-guard-v1','price':price,'delta_6m_usdt':d6,'delta_15m_usdt':d15,
        'range_6m_usdt':range6,'range_15m_usdt':range15,
        'state_рус':state,'rapid_move_observed':rapid,'stale_forecast_cannot_describe_current_market_as_quiet':rapid,
        'anchor_utc':dt.datetime.fromtimestamp(anchor_ms/1000,dt.timezone.utc).isoformat(),
        'received_utc':dt.datetime.fromtimestamp(received_ms/1000,dt.timezone.utc).isoformat(),
        'thresholds':{'6m_usdt':MOVE_6M_USDT,'15m_usdt':MOVE_15M_USDT},
        'observed_detection_not_a_prediction':True,'trading_authority':False,'full_system_ready':False}
