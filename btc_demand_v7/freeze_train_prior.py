"""Frozen train-only FIRST-passage prior, not oracle TEST prevalence.

Source: signed v6 closed 1m spot raw (verified before use). Strictly end all
training targets before September 28 2026 00:00 UTC.
"""
import argparse,datetime as dt,gzip,hashlib,json,pathlib
from btc_demand_v7.event_semantics import BARRIERS,first_passage
UTC=dt.timezone.utc
CUTOFF=dt.datetime(2026,9,28,tzinfo=UTC)
SOURCE_RESEARCH_RUN=38167948896

def compute(rows):
    ts={int(r[0]):r for r in rows}
    keys=sorted(ts)
    out={}
    cutoff=int(CUTOFF.timestamp()*1000)
    for horizon,(minutes,threshold) in BARRIERS.items():
        count={"UP_FIRST":0,"DOWN_FIRST":0,"NEITHER":0,
               "AMBIGUOUS_SAME_MINUTE":0}
        checked=0;incomplete=0
        step=minutes*60000
        for t in keys:
            # fixed phase non-overlapping anchors only, no overlapping 5m samples
            if (t+60000) % step!=0:continue
            anchor=t+60000
            if anchor+minutes*60000>=cutoff:continue
            forward=[ts.get(anchor+i*60000) for i in range(minutes)]
            if any(r is None for r in forward):
                incomplete+=1;continue
            ref=float(ts[t][4])
            r=first_passage(dt.datetime.fromtimestamp(anchor/1000,UTC),
                            ref,forward,horizon)
            count[r["direction"]]+=1;checked+=1
        valid=checked-count["AMBIGUOUS_SAME_MINUTE"]
        if valid<80:raise RuntimeError("insufficient TRAIN prior independent windows")
        out[horizon]={"n_independent_train_windows":checked,
            "n_unambiguous":valid,"count":count,
            "p_up_first_train":count["UP_FIRST"]/valid,
            "p_down_first_train":count["DOWN_FIRST"]/valid,
            "p_neither_train":count["NEITHER"]/valid,
            "n_raw_incomplete":incomplete}
    return {"schema":"btc-v7r2-frozen-first-touch-train-priors",
            "train_target_end_before_utc":CUTOFF.isoformat(),
            "source_signed_research_run":SOURCE_RESEARCH_RUN,
            "source_binance_1m":"closed 1m klines",
            "fixed_phases_not_overlapping":True,
            "treat_ambiguous_as_separate_label":True,
            "preregister_no_test_prevalence":True,
            "event_priors":out,
            "trading_authority":False}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--raw",required=True);p.add_argument("--out",required=True)
    a=p.parse_args()
    with gzip.open(a.raw,"rt") as f:rows=json.load(f)
    report=compute(rows)
    text=json.dumps(report,sort_keys=True,indent=2)+"\n"
    pathlib.Path(a.out).write_text(text)
    print("V7R2_FROZEN_TRAIN_PRIORS",json.dumps(report["event_priors"],sort_keys=True))
if __name__=="__main__":main()
