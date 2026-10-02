def macro_score(ctx):
    score=0.0; used=[]
    for e in (ctx or {}).get("calendar",{}).get("events",[]):
        if e.get("status")!="RELEASED": continue
        a=e.get("actual"); c=e.get("consensus")
        if not isinstance(a,(int,float)) or not isinstance(c,(int,float)) or not c: continue
        s=(float(a)-float(c))/abs(float(c)); typ=e.get("type",""); d=0.0
        if typ=="INITIAL_JOBLESS_CLAIMS": d=s
        elif typ in ("ISM_MANUFACTURING","ISM_SERVICES","EMPLOYMENT_SITUATION","ADP_EMPLOYMENT","CORE_PCE","CPI","PPI"): d=-s
        if d:
            v=max(-0.7,min(0.7,d*8.0)); score+=v
            used.append({"type":typ,"surprise":s,"btc_contribution":v})
    return max(-1.0,min(1.0,score)),used
