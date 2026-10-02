from __future__ import annotations
import math
from datetime import datetime, timezone\nfrom macro_signal import macro_score

def clip(x,a=-1.0,b=1.0): return max(a,min(b,float(x)))
def pct(a,b): return 100.0*(float(a)/float(b)-1.0) if float(b) else 0.0
def sm(up,rg,dn):
    m=max(up,rg,dn); e=[math.exp(x-m) for x in (up,rg,dn)]; s=sum(e)
    return {"upside":e[0]/s,"range":e[1]/s,"downside":e[2]/s}

def _valid(ctx,name):
    x=(ctx or {}).get("factors",{}).get(name,{})
    return x if isinstance(x,dict) and x.get("status")=="VALID" else {}

def _v(ctx,name,key="value"):
    x=_valid(ctx,name); v=x.get(key)
    return float(v) if isinstance(v,(int,float)) else None

def candle_features(c):
    if len(c)<169: raise ValueError("169 closed 1h candles required")
    c=c[-169:]; cl=[float(x["close"]) for x in c]; hi=[float(x["high"]) for x in c]; lo=[float(x["low"]) for x in c]
    vol=[float(x["volume"]) for x in c]; tk=[float(x["taker_buy_base"]) for x in c]; trd=[float(x["trades"]) for x in c]
    ret=lambda n:pct(cl[-1],cl[-1-n])
    tr=[]
    for i in range(len(c)-24,len(c)):
        p=cl[i-1]; tr.append(max(hi[i]-lo[i],abs(hi[i]-p),abs(lo[i]-p)))
    atr=max(0.05,100.0*sum(tr)/len(tr)/cl[-1])
    imb=lambda w: sum(2*tk[i]-vol[i] for i in range(len(c)-w,len(c)))/max(sum(vol[-w:]),1e-9)
    def z(a,w):
        x=[math.log1p(max(0.0,v)) for v in a[-w:]]; m=sum(x)/w; sd=math.sqrt(sum((v-m)**2 for v in x)/w)
        return 0.0 if sd==0 else (x[-1]-m)/sd
    pos=sum(cl[i]>cl[i-1] for i in range(len(c)-6,len(c)))/6
    hh=sum(hi[i]>hi[i-1] for i in range(len(c)-5,len(c)))/5
    hl=sum(lo[i]>lo[i-1] for i in range(len(c)-5,len(c)))/5
    b24=pct(cl[-1],max(hi[-25:-1])); b72=pct(cl[-1],max(hi[-73:-1]))
    tech=.18*math.tanh(ret(3)/(1.2*atr))+.22*math.tanh(ret(6)/(1.8*atr))+.18*math.tanh(ret(12)/(2.8*atr))+.14*math.tanh(ret(24)/(4*atr))+.16*(2*pos-1)+.06*(2*hh-1)+.06*(2*hl-1)
    structure=.55*math.tanh(b24/max(.08,.55*atr))+.25*math.tanh(b72/max(.12,.8*atr))+.2*(2*hl-1)
    flow=.45*clip(imb(1)*3)+.30*clip(imb(4)*3)+.125*clip(z(vol,24)/3)+.125*clip(z(trd,24)/3)
    return {"technical":clip(tech),"structure":clip(structure),"flow":clip(flow),"ret1":ret(1),"ret6":ret(6),"ret24":ret(24),"atr24":atr,"breakout24":b24,"breakout72":b72,"persistence":2*pos-1,"imb1":imb(1),"imb4":imb(4)}

def external(now,prev,price_ret):
    oi0=_v(prev,"open_interest","value_btc"); oi1=_v(now,"open_interest","value_btc")
    oi=pct(oi1,oi0) if oi0 not in (None,0) and oi1 is not None else 0.0
    confirm=math.tanh(abs(oi)/1.5)*(1 if price_ret>0 else -1 if price_ret<0 else 0)
    if oi<0: confirm*=-.5
    funding=100*(_v(now,"funding") or 0.0); crowd=0.0
    if funding>.015: crowd=-math.tanh((funding-.015)/.02)
    elif funding<-.015: crowd=math.tanh((-funding-.015)/.02)
    def chg(name,key="value"):
        a=_v(now,name,key); b=_v(prev,name,key); return pct(a,b) if a is not None and b not in (None,0) else 0.0
    dxy=chg("dxy"); nq=chg("nasdaq_futures")
    y1=_v(now,"us10y"); y0=_v(prev,"us10y"); ybps=(y1-y0)*100 if y1 is not None and y0 is not None else 0.0
    etf=_v(now,"etf_flows","numeric_value") or 0.0
    score=.34*confirm+.14*crowd+.18*clip(-dxy/.35)+.16*clip(nq/.8)+.10*clip(-ybps/12)+.08*math.tanh(etf/250)
    return {"score":clip(score),"oi_change_pct":oi,"funding_pct":funding,"dxy_change_pct":dxy,"nasdaq_change_pct":nq,"us10y_change_bps":ybps,"etf_usd_m":etf}

def forecast(candles,issued_at,ctx_now=None,ctx_prev=None):
    if isinstance(issued_at,str): issued_at=datetime.fromisoformat(issued_at.replace("Z","+00:00"))
    issued_at=issued_at.astimezone(timezone.utc)
    for ctx in (ctx_now,ctx_prev):
        if ctx and datetime.fromisoformat(ctx["captured_at_utc"].replace("Z","+00:00")).astimezone(timezone.utc)>issued_at: raise ValueError("future context forbidden")
    p=candle_features(candles); e=external(ctx_now,ctx_prev,p["ret1"]); macro,macro_used=macro_score(ctx_now)
    transition=clip(abs(p["ret6"])/(p["atr24"]*2.2),0,1); breakout=clip(max(0,p["breakout24"])/(p["atr24"]*.8),0,1)
    score=clip(.42*p["technical"]+.21*p["structure"]+.13*p["flow"]+.16*e["score"]+.08*macro+.10*math.copysign(transition,p["ret6"] or 1)+.08*breakout+.05*p["persistence"])
    probs=sm(2.7*score,1.45-2.15*abs(score),-2.7*score)
    wait=int(round(100*clip(.5+.42*score+.18*breakout+.12*max(0,p["persistence"]),0,1)))
    return {"schema":"btc-regime-challenger-v1","issued_at_utc":issued_at.isoformat(),"regime_score":score,"regime_probabilities":probs,"regime_label":max(probs,key=probs.get),"transition_strength":transition,"breakout_strength":breakout,"risk_waiting_for_lower_price_pct":wait,"components":{"technical":p["technical"],"structure":p["structure"],"market_microstructure":p["flow"],"external_market":e["score"],"macro_surprise":macro},"price_features":p,"external_features":e,"macro_events_used":macro_used,"calibration_status":"UNVALIDATED_PROSPECTIVE_CHALLENGER","trading_authority":False}
