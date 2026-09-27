"""Leakage-safe closed-candle feature contracts for v2.9.30 multi-horizon uplift.

The same pure functions are used by historical research and live snapshot
construction. Inputs are contiguous, already-closed 1h candles ending at the
issuance anchor. No future or mutable screening spot is consulted.
"""
from __future__ import annotations
import math
from datetime import datetime, timezone

H4_FEATURES=(
'weekend','hour_cos','rv_48h','rv_72h','trades_z_24h','vol_z_24h','atr_ratio_4_24','ret_24h','atr_24h_pct','close_loc','close_loc_mean_4h','imb_72h',
'range_pos_12h','hour_sin','imb_1h','atr_12h_pct','vol_ratio_4_24','imb_accel_1_24','imb_accel_4_24','imb_24h','atr_4h_pct','dist_low_24h_pct','imb_4h','rv_8h','slope_72h_logpctph','candle_range_pct','rv_12h','phase4_cos','ret_3h','trend_vol_24','rv_24h','dist_high_24h_pct','ret_6h','range_pos_24h','ret_8h','trades_z_4h','range_pos_72h','range_pos_4h','vs_sma_72h_pct','vs_sma_4h_pct','ret_2h','slope_6h_logpctph','vol_z_4h','slope_12h_logpctph','phase4_sin','slope_24h_logpctph','rv_4h','body_pct','ret_1h','body_mean_4h','ret_4h','imb_12h','vs_sma_12h_pct','ret_12h','vs_sma_24h_pct','ret_48h','ret_72h')

H24_FEATURES=('dow_cos','dow_sin','rv_168h','imb_168h','dist_low_72h_pct','atr_72h_pct','slope_168h_logpctph','rv_48h','rv_72h','vol_ratio_12_72','atr_24h_pct','slope_72h_logpctph')

def _f(c,key): return float(c[key])
def _ret(candles,n): return 100.0*(_f(candles[-1],'close')/_f(candles[-1-n],'close')-1.0)
def _rv(candles,w):
    a=candles[-(w+1):]; r=[math.log(_f(a[i],'close')/_f(a[i-1],'close')) for i in range(1,len(a))]; m=sum(r)/len(r)
    return 100.0*math.sqrt(sum((x-m)**2 for x in r)/len(r))
def _atr_pct(candles,w):
    a=candles[-(w+1):]; tr=[]
    for i in range(1,len(a)):
        p=_f(a[i-1],'close'); tr.append(max(_f(a[i],'high')-_f(a[i],'low'),abs(_f(a[i],'high')-p),abs(_f(a[i],'low')-p)))
    return 100.0*(sum(tr)/len(tr))/_f(candles[-1],'close')
def _range_pos(candles,w):
    a=candles[-w:]; h=max(_f(x,'high') for x in a); l=min(_f(x,'low') for x in a); return 0.5 if h==l else (_f(candles[-1],'close')-l)/(h-l)
def _dist_high(candles,w):
    h=max(_f(x,'high') for x in candles[-w:]); return 100.0*(_f(candles[-1],'close')/h-1.0)
def _dist_low(candles,w):
    l=min(_f(x,'low') for x in candles[-w:]); return 100.0*(_f(candles[-1],'close')/l-1.0)
def _vs_sma(candles,w):
    a=[_f(x,'close') for x in candles[-w:]]; return 100.0*(a[-1]/(sum(a)/w)-1.0)
def _slope(candles,w):
    y=[math.log(_f(x,'close')) for x in candles[-w:]]; xm=(w-1)/2.0; ym=sum(y)/w; den=sum((i-xm)**2 for i in range(w))
    return 100.0*sum((i-xm)*(v-ym) for i,v in enumerate(y))/den
def _z(candles,w,key):
    a=[math.log1p(max(0.0,_f(x,key))) for x in candles[-w:]]; m=sum(a)/w; sd=math.sqrt(sum((x-m)**2 for x in a)/w); return 0.0 if sd==0 else (a[-1]-m)/sd
def _imb(candles,w):
    a=candles[-w:]; denom=sum(_f(x,'volume') for x in a)
    return 0.0 if denom<=0 else sum(2.0*_f(x,'taker_buy_base')-_f(x,'volume') for x in a)/denom
def _body(c): return 100.0*(_f(c,'close')/_f(c,'open')-1.0)
def _cloc(c):
    r=_f(c,'high')-_f(c,'low'); return 0.0 if r==0 else 2.0*(_f(c,'close')-_f(c,'low'))/r-1.0

def compute(candles, issued_at):
    if len(candles)<169: raise ValueError('v2.9.30 features require 169 closed 1h candles')
    c=candles[-169:]
    if isinstance(issued_at,str): issued_at=datetime.fromisoformat(issued_at.replace('Z','+00:00'))
    if issued_at.tzinfo is None: raise ValueError('issued_at timezone required')
    issued_at=issued_at.astimezone(timezone.utc); hour=issued_at.hour; dow=issued_at.weekday()
    out={}
    for n in (1,2,3,4,6,8,12,24,48,72): out[f'ret_{n}h']=_ret(c,n)
    for w in (4,8,12,24,48,72,168): out[f'rv_{w}h']=_rv(c,w)
    for w in (4,12,24,72): out[f'atr_{w}h_pct']=_atr_pct(c,w)
    for w in (4,12,24,72): out[f'range_pos_{w}h']=_range_pos(c,w)
    for w in (24,72):
        out[f'dist_high_{w}h_pct']=_dist_high(c,w); out[f'dist_low_{w}h_pct']=_dist_low(c,w)
    for w in (4,12,24,72): out[f'vs_sma_{w}h_pct']=_vs_sma(c,w)
    for w in (6,12,24,72,168): out[f'slope_{w}h_logpctph']=_slope(c,w)
    for w in (4,24):
        out[f'vol_z_{w}h']=_z(c,w,'volume'); out[f'trades_z_{w}h']=_z(c,w,'trades')
    for w in (1,4,12,24,72,168): out[f'imb_{w}h']=_imb(c,w)
    out['imb_accel_1_24']=out['imb_1h']-out['imb_24h']; out['imb_accel_4_24']=out['imb_4h']-out['imb_24h']
    last=c[-1]; out['candle_range_pct']=100.0*(_f(last,'high')-_f(last,'low'))/_f(last,'close'); out['body_pct']=_body(last); out['close_loc']=_cloc(last)
    out['body_mean_4h']=sum(_body(x) for x in c[-4:])/4.0; out['close_loc_mean_4h']=sum(_cloc(x) for x in c[-4:])/4.0
    out['vol_ratio_4_24']=out['rv_4h']/out['rv_24h'] if out['rv_24h'] else 0.0; out['vol_ratio_12_72']=out['rv_12h']/out['rv_72h'] if out['rv_72h'] else 0.0
    out['atr_ratio_4_24']=out['atr_4h_pct']/out['atr_24h_pct'] if out['atr_24h_pct'] else 0.0; out['trend_vol_24']=out['slope_24h_logpctph']/max(out['rv_24h'],0.05)  # 5bp vol floor; below frozen-history minimum, prevents quiet-market singularity
    out['hour_sin']=math.sin(2*math.pi*hour/24); out['hour_cos']=math.cos(2*math.pi*hour/24); out['weekend']=1.0 if dow>=5 else 0.0
    out['dow_sin']=math.sin(2*math.pi*dow/7); out['dow_cos']=math.cos(2*math.pi*dow/7)
    out['phase4_sin']=math.sin(2*math.pi*(hour%4)/4); out['phase4_cos']=math.cos(2*math.pi*(hour%4)/4)
    needed=set(H4_FEATURES)|set(H24_FEATURES)
    missing=[k for k in needed if k not in out or not math.isfinite(float(out[k]))]
    if missing: raise ValueError('invalid v2.9.30 feature(s): '+','.join(missing))
    return out
