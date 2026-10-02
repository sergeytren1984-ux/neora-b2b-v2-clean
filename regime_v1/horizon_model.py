from __future__ import annotations
import math

def _clip(x,a=-1.0,b=1.0): return max(a,min(b,float(x)))
def _softmax(up,rg,dn):
    m=max(up,rg,dn); e=[math.exp(x-m) for x in (up,rg,dn)]; s=sum(e)
    return {"upside":e[0]/s,"range":e[1]/s,"downside":e[2]/s}

def horizon_outputs(regime):
    p=regime["price_features"]; e=regime["external_features"]; c=regime["components"]
    base=float(regime["regime_score"])
    atr=max(float(p["atr24"]),0.05)

    # 1h: fast flow/external context dominates; continuation is penalized after a stretched 1h bar.
    stretch1=_clip(abs(p["ret1"])/(atr*1.5),0,1)
    s1=_clip(.52*base+.20*c["market_microstructure"]+.18*c["external_market"]+.10*math.tanh(p["ret1"]/atr)-.10*math.copysign(stretch1,p["ret1"] or 1))
    # 4h: transition/persistence/breakout are intentionally dominant.
    s4=_clip(.52*base+.18*c["structure"]+.12*c["market_microstructure"]+.10*regime["transition_strength"]*math.copysign(1,p["ret6"] or 1)+.08*regime["breakout_strength"])
    # 24h: slower structure, ETF/macro/external market matter more than the latest candle.
    etf=math.tanh(float(e.get("etf_usd_m",0.0))/300.0)
    s24=_clip(.46*base+.20*c["structure"]+.18*c["external_market"]+.10*etf+.06*c.get("macro_surprise",0.0))

    def probs(score,h):
        # Wider horizons require stronger score before a directional class dominates.
        k={"1h":2.6,"4h":3.0,"24h":2.5}[h]
        neutral={"1h":1.65,"4h":1.45,"24h":1.30}[h]
        penalty={"1h":2.0,"4h":1.7,"24h":1.5}[h]
        return _softmax(k*score,neutral-penalty*abs(score),-k*score)
    thresholds={"1h":max(.12,.55*atr),"4h":max(.25,1.20*atr),"24h":max(.60,2.20*atr)}
    return {
      "1h":{"score":s1,"probabilities":probs(s1,"1h"),"threshold_pct":thresholds["1h"]},
      "4h":{"score":s4,"probabilities":probs(s4,"4h"),"threshold_pct":thresholds["4h"]},
      "24h":{"score":s24,"probabilities":probs(s24,"24h"),"threshold_pct":thresholds["24h"]},
    }
