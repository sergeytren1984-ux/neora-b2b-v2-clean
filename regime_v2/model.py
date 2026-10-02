from __future__ import annotations
import math

CLASSES=("upside","range","downside")

def clip(x,a=-1.0,b=1.0): return max(a,min(b,float(x)))
def pct(a,b): return 100.0*(float(a)/float(b)-1.0) if float(b) else 0.0

def softmax(up,rg,dn):
    m=max(up,rg,dn); e=[math.exp(x-m) for x in (up,rg,dn)]; s=sum(e)
    return {"upside":e[0]/s,"range":e[1]/s,"downside":e[2]/s}

def candle_features(c):
    if len(c)<169: raise ValueError("169 closed 1h candles required")
    c=c[-169:]
    cl=[float(x["close"]) for x in c]; hi=[float(x["high"]) for x in c]; lo=[float(x["low"]) for x in c]
    vol=[float(x["volume"]) for x in c]; tk=[float(x["taker_buy_base"]) for x in c]; trd=[float(x["trades"]) for x in c]
    for i,x in enumerate(c):
        if float(x["low"])>min(float(x["open"]),float(x["close"])) or float(x["high"])<max(float(x["open"]),float(x["close"])):
            raise ValueError(f"OHLC invariant failed at {i}")
        if float(x["volume"])<0 or int(x["trades"])<0: raise ValueError("negative market activity")
    ret=lambda n:pct(cl[-1],cl[-1-n])
    trs=[]
    for i in range(len(c)-24,len(c)):
        p=cl[i-1]; trs.append(max(hi[i]-lo[i],abs(hi[i]-p),abs(lo[i]-p)))
    atr=max(0.05,100.0*sum(trs)/len(trs)/cl[-1])
    def imb(w):
        den=sum(vol[-w:])
        return 0.0 if den<=0 else sum(2*tk[i]-vol[i] for i in range(len(c)-w,len(c)))/den
    def z(a,w):
        x=[math.log1p(max(0.0,v)) for v in a[-w:]]; m=sum(x)/w
        sd=math.sqrt(sum((v-m)**2 for v in x)/w)
        return 0.0 if sd==0 else (x[-1]-m)/sd
    pos=sum(cl[i]>cl[i-1] for i in range(len(c)-6,len(c)))/6.0
    hh=sum(hi[i]>hi[i-1] for i in range(len(c)-5,len(c)))/5.0
    hl=sum(lo[i]>lo[i-1] for i in range(len(c)-5,len(c)))/5.0
    ll=sum(lo[i]<lo[i-1] for i in range(len(c)-5,len(c)))/5.0
    lh=sum(hi[i]<hi[i-1] for i in range(len(c)-5,len(c)))/5.0
    prev24h=max(hi[-25:-1]); prev24l=min(lo[-25:-1]); prev72h=max(hi[-73:-1]); prev72l=min(lo[-73:-1])
    up24=pct(cl[-1],prev24h); dn24=pct(prev24l,cl[-1])
    up72=pct(cl[-1],prev72h); dn72=pct(prev72l,cl[-1])
    tech=.20*math.tanh(ret(3)/(1.2*atr))+.26*math.tanh(ret(6)/(1.8*atr))+.20*math.tanh(ret(12)/(2.8*atr))+.14*math.tanh(ret(24)/(4*atr))+.20*(2*pos-1)
    up_structure=.45*math.tanh(max(0,up24)/max(.08,.55*atr))+.20*math.tanh(max(0,up72)/max(.12,.8*atr))+.20*(2*hl-1)+.15*(2*hh-1)
    down_structure=.45*math.tanh(max(0,dn24)/max(.08,.55*atr))+.20*math.tanh(max(0,dn72)/max(.12,.8*atr))+.20*(2*lh-1)+.15*(2*ll-1)
    structure=clip(up_structure-down_structure)
    flow=.45*clip(imb(1)*3)+.30*clip(imb(4)*3)+.125*clip(z(vol,24)/3)+.125*clip(z(trd,24)/3)
    persistence=clip((2*pos-1)+.5*((hl+hh)-(ll+lh)))
    returns=[math.log(cl[i]/cl[i-1]) for i in range(len(cl)-48,len(cl))]
    mu=sum(returns)/len(returns); sd=math.sqrt(sum((r-mu)**2 for r in returns)/len(returns)) or 1e-9
    gp=gn=0.0
    for r in returns[-12:]:
        zret=(r-mu)/sd
        gp=max(0.0,gp+zret-.25); gn=max(0.0,gn-zret-.25)
    cp=clip((gp-gn)/3.0)
    transition=clip(abs(ret(6))/(atr*2.2),0,1)* (1 if ret(6)>=0 else -1)
    breakout=clip(max(up24,dn24)/(atr*.8),0,1) * (1 if up24>=dn24 else -1)
    return {
      "technical":clip(tech),"structure":structure,"flow":clip(flow),"persistence":persistence,
      "transition":transition,"breakout":breakout,"change_point":cp,
      "ret_1h":ret(1),"ret_3h":ret(3),"ret_6h":ret(6),"ret_12h":ret(12),"ret_24h":ret(24),
      "atr24_pct":atr,"breakout_up_24h_pct":up24,"breakout_down_24h_pct":dn24,
      "breakout_up_72h_pct":up72,"breakout_down_72h_pct":dn72,
      "taker_imbalance_1h":imb(1),"taker_imbalance_4h":imb(4)
    }

def _value(ctx,name,key):
    f=(ctx.get("factors") or {}).get(name,{})
    v=f.get(key)
    return float(v) if isinstance(v,(int,float)) else None

def external_features(pair):
    now=pair["current"]; prev=pair["previous"]; elapsed=float(pair["elapsed_seconds"])
    if elapsed<=0: raise ValueError("elapsed context time invalid")
    hour_scale=3600.0/elapsed
    curstat=pair["current_factor_status"]; prevstat=pair["previous_factor_status"]
    signals=[]; details={}
    def availability(name):
        return curstat.get(name,{}).get("available") and prevstat.get(name,{}).get("available")
    if availability("open_interest"):
        a=_value(now,"open_interest","value_btc"); b=_value(prev,"open_interest","value_btc")
        if a is not None and b not in (None,0):
            oi=pct(a,b)*hour_scale
            price_sign=1 if pair.get("price_ret_1h",0)>0 else -1 if pair.get("price_ret_1h",0)<0 else 0
            confirm=math.tanh(abs(oi)/1.5)*price_sign
            if oi<0: confirm*=-.5
            signals.append((.34,confirm)); details["oi_change_pct_per_hour"]=oi
    if curstat.get("funding",{}).get("available"):
        funding=100.0*(_value(now,"funding","value") or 0.0); crowd=0.0
        if funding>.015: crowd=-math.tanh((funding-.015)/.02)
        elif funding<-.015: crowd=math.tanh((-funding-.015)/.02)
        signals.append((.14,crowd)); details["funding_pct"]=funding; details["funding_crowding"]=crowd
    def idx_signal(name,weight,scale,sign=1):
        if not availability(name): return
        a=_value(now,name,"value"); b=_value(prev,name,"value")
        if a is None or b in (None,0): return
        ch=pct(a,b)*hour_scale
        signals.append((weight,clip(sign*ch/scale))); details[name+"_change_pct_per_hour"]=ch
    idx_signal("dxy",.18,.35,-1); idx_signal("nasdaq_futures",.16,.8,1)
    if availability("us10y"):
        a=_value(now,"us10y","value"); b=_value(prev,"us10y","value")
        if a is not None and b is not None:
            bps=(a-b)*100.0*hour_scale
            signals.append((.10,clip(-bps/12.0))); details["us10y_change_bps_per_hour"]=bps
    if curstat.get("etf_flows",{}).get("available"):
        etf=_value(now,"etf_flows","numeric_value")
        if etf is not None:
            signals.append((.08,math.tanh(etf/250.0))); details["etf_usd_m"]=etf
    if not signals: return {"score":None,"available_weight":0.0,"details":details}
    w=sum(x[0] for x in signals)
    return {"score":clip(sum(a*b for a,b in signals)/w),"available_weight":w,"details":details}

def horizon_outputs(score,features,external_score):
    atr=features["atr24_pct"]
    s1=clip(.55*score+.20*features["flow"]+.15*(external_score or 0)+.10*math.tanh(features["ret_1h"]/atr))
    s4=clip(.55*score+.18*features["structure"]+.12*features["transition"]+.10*features["breakout"]+.05*features["change_point"])
    s24=clip(.58*score+.22*features["structure"]+.12*(external_score or 0)+.08*features["persistence"])
    def probs(s,h):
        k={"1h":2.5,"4h":2.8,"24h":2.4}[h]; neutral={"1h":1.7,"4h":1.5,"24h":1.35}[h]; pen={"1h":2.0,"4h":1.8,"24h":1.5}[h]
        return softmax(k*s,neutral-pen*abs(s),-k*s)
    return {
      "1h":{"score":s1,"probabilities":probs(s1,"1h"),"threshold_pct":max(.12,.55*atr)},
      "4h":{"score":s4,"probabilities":probs(s4,"4h"),"threshold_pct":max(.25,1.20*atr)},
      "24h":{"score":s24,"probabilities":probs(s24,"24h"),"threshold_pct":max(.60,2.20*atr)}
    }

def forecast(candles,context_pair,protocol):
    f=candle_features(candles); context_pair=dict(context_pair); context_pair["price_ret_1h"]=f["ret_1h"]
    ext=external_features(context_pair)
    external_component=ext["score"] if ext["score"] is not None else 0.0
    c=protocol["regime_formula"]
    score=clip(c["technical"]*f["technical"]+c["structure"]*f["structure"]+c["market_microstructure"]*f["flow"]+
               c["external_market"]*external_component+c["transition"]*f["transition"]+c["breakout"]*f["breakout"]+
               c["persistence"]*f["persistence"]+c["change_point"]*f["change_point"])
    regime=softmax(2.7*score,1.75-1.95*abs(score),-2.7*score)
    return {
      "schema":"btc-regime-v2-shadow-output-v1","regime_score":score,"regime_probabilities":regime,
      "regime_label":max(regime,key=regime.get),"components":{k:f[k] for k in ("technical","structure","flow","transition","breakout","persistence","change_point")},
      "external":ext,"macro":{"status":"DISABLED_PENDING_TIMESTAMPED_CALIBRATION","score":None},
      "horizons":horizon_outputs(score,f,ext["score"]),"features":f,
      "calibration_status":"UNVALIDATED_PROSPECTIVE_SHADOW","trading_authority":False
    }
