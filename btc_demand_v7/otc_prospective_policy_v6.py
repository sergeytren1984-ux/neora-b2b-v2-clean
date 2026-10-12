"""Precommitted research-only BTC buy-now vs wait-1h OTC cash-flow proxy.

One deterministic policy frozen BEFORE its future signed R5 due grid:
  signed eligible UP pressure -> BUY_NOW, else WAIT_1H.
It is NOT a forecasting model, not an actual operator quote, nor trading
authority. No look-ahead: action depends only on signed early event,
while later executable price/fill/outcome is independently derived from
first-passage raw 1m futures after verified public GitHub delivery.

Wealth comparison is apples-to-apples USDT mark-to-market at +4h:
    terminal USDT = unspent cash + filled BTC * actual +4h spot.
An operator refusing moves over 300-500 USD is a hypothetical guard,
not a verified operator decision; OTC markup uses 300-400 USD scenarios.
Real full/partial fills, negotiation latency and operator quotes are
NOT observable from public Binance candles.
"""
from __future__ import annotations
import datetime as dt,json,math,hashlib
def when(value):
    timestamp=dt.datetime.fromisoformat(value.replace("Z","+00:00")) if isinstance(value,str) else value
    if not isinstance(timestamp,dt.datetime) or timestamp.tzinfo is None:
        raise ValueError("must supply offset-aware time")
    return timestamp.astimezone(UTC)

def digest(value):
    data=json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False)
    return hashlib.sha256((data+chr(10)).encode()).hexdigest()

UTC=dt.timezone.utc
BUDGET=147600.0
GUARDS=(300.,500.)
PREMIUMS=(300.,400.)
EXECUTE_AFTER_MINUTES=60
WAIT_BEFORE_REQUEST_MINUTES=60
PATH_MINUTES=240
SCHEMA="btc-v7r5-precommitted-otc-cash-preserving-shadow-v2"
MODEL_SHA="d6acb83d45ea484d2f2c88b725faedf3de97775d"
REGISTERED_START="2026-10-13T00:00:00+00:00"
REGISTERED_END="2026-10-20T00:00:00+00:00"

def commitment():
    return {
        "schema":SCHEMA,
        "source_sha":MODEL_SHA,
        "source_epoch_start":REGISTERED_START,
        "source_epoch_end":REGISTERED_END,
        "policy_before_future_outcomes":"BUY_NOW only if signed on-time, non-recovery, not-already-moved UP warning; otherwise WAIT_1H",
        "buy_request_at":"verified GitHub publication",
        "buy_execution_at":"first complete 1m bar end approx +60m after publication",
        "wait_request_at":"first complete 1m bar end approx +60m after publication",
        "wait_execution_at":"first complete 1m bar end approx +120m after publication",
        "mark_at":"first complete 1m bar end approx +240m after publication",
        "cash_budget_usdt":BUDGET,
        "otc_markups_per_btc_usdt":list(PREMIUMS),
        "operator_price_movement_guards_usdt":list(GUARDS),
        "real_operator_quote_logged":False,
        "real_execution_fills_logged":False,
        "economic_proxy_not_trade_grade":True,
        "allow_retroactive_policy_changes":False,
        "trading_authority":False,
        "model_skill_proven":False,
    }

def require_float(value,label):
    n=float(value)
    if not math.isfinite(n) or n<=0:
        raise ValueError("invalid "+label)
    return n

def source_minutes(raw,public_at):
    if raw.get("schema")!="btc-v7r3-closed-1m-forward-source-v2" or raw.get("symbol")!="BTCUSDT":
        raise ValueError("substituted market source instrument/schema")
    if when(raw["actual_publication_utc"])!=when(public_at):
        raise ValueError("raw source public time differs from signed delivery")
    rows=raw["rows"]
    if len(rows)!=PATH_MINUTES:raise ValueError("incomplete 4h first minute raw")
    reference=raw["reference_row"]
    ref_close=int(reference[6])+1
    if ref_close!=int(reference[0])+60000:
        raise ValueError("invalid reference closed minute")
    if ref_close>int(when(public_at).timestamp()*1000):
        raise ValueError("reference price after public delivery")
    result=[]
    prev=None
    for row in rows:
        open_ms=int(row[0])
        if int(row[6])+1!=open_ms+60000:
            raise ValueError("forged unclosed forward minute")
        if prev is not None and open_ms-prev!=60000:
            raise ValueError("missing or overlapping future minute")
        op,hi,lo,cl=map(float,row[1:5])
        if not all(math.isfinite(n) for n in (op,hi,lo,cl)) or not 0<lo<=min(op,cl)<=max(op,cl)<=hi:
            raise ValueError("malformed forward OHLC")
        result.append(cl)
        prev=open_ms
    # The first full minute starts strictly after public delivery:
    # never obtain a within-minute half-bar execution price.
    if int(rows[0][0])<int(when(public_at).timestamp()*1000):
        raise ValueError("forward source includes uncompleted pre-delivery minute")
    return (require_float(reference[4],"public reference"),
            result[59],result[119],result[239])

def precommitted_action(event,delivered):
    if (event.get("status")!="SIGNED_STATE_PUBLISHED"
        or event.get("model_source_sha")!=MODEL_SHA):
        raise ValueError("unregistered forecast source")
    t=when(event["anchor_utc"]);public=when(delivered)
    if not(t<=when(event["issued_at_utc"])<=public
           and t+dt.timedelta(minutes=3)<=public<=t+dt.timedelta(minutes=13)):
        raise ValueError("late or fabricated public signal")
    diag=event.get("diagnostic")
    if not isinstance(diag,dict):raise ValueError("missing numerical diagnostic")
    if diag.get("alert") is True and diag.get("warning_side")=="UP" and (
        diag.get("price_already_moved") is False and event.get("recovery") is None):
        return "BUY_NOW"
    return "WAIT_1H"

def simulated_execution(price_on_request,price_on_execution,guard,premium):
    reference=require_float(price_on_request,"operator request reference")
    execution=require_float(price_on_execution,"execution reference")
    if not 300<=guard<=500 or not 300<=premium<=400:
        raise ValueError("unregistered OTC constraint")
    if abs(reference-execution)>guard:
        return {"BTC":0.,"USDT":BUDGET,"request_rejected_proxy":True}
    return {"BTC":BUDGET/(execution+premium),"USDT":0.,"request_rejected_proxy":False}

def compare_pair(event,delivery,raw):
    published=when(delivery["public_delivery_utc"])
    if (delivery.get("source_signal_sha256")!=digest(event)
        or delivery.get("model_source_sha")!=MODEL_SHA
        or delivery.get("slot_id")!=event.get("slot_id")):
        raise ValueError("forged publication receipt/source")
    action=precommitted_action(event,published)
    before,one,two,four=source_minutes(raw,published)
    out={}
    for guard in GUARDS:
        for premium in PREMIUMS:
            buy=simulated_execution(before,one,guard,premium)
            wait=simulated_execution(one,two,guard,premium)
            selected=buy if action=="BUY_NOW" else wait
            benchmark=buy
            def wealth(fill):
                return fill["BTC"]*four+fill["USDT"]
            out[str(int(guard))+"_"+str(int(premium))]={
                "guard_usdt":guard,"markup_per_btc_usdt":premium,
                "precommitted_action":action,
                "buy_now":buy,"wait_1h":wait,
                "selected_wealth_4h_usdt":wealth(selected),
                "always_buy_now_wealth_4h_usdt":wealth(benchmark),
                "always_wait_1h_wealth_4h_usdt":wealth(wait),
                "policy_gain_vs_always_buy_usdt":wealth(selected)-wealth(benchmark),
                "policy_gain_vs_always_wait_usdt":wealth(selected)-wealth(wait),
                "real_operator_fill_verified":False,
                "cash_not_equated_to_zero_when_rejected":True
            }
    return {
        "schema":"btc-v7r5-otc-paired-mark-to-market-4h-v1",
        "slot_id":event["slot_id"],
        "public_delivery_utc":published.isoformat(),
        "precommitted_action":action,
        "public_reference_spot":before,
        "buy_now_execution_spot_after1h":one,
        "wait_execution_spot_after2h":two,
        "terminal_spot_after4h":four,
        "scenarios":out,"actual_operator_quotes":False,
        "actual_partial_fills":False,
        "trading_authority":False
    }
