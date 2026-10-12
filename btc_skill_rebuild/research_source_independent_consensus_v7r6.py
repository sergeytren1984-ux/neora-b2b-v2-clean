"""v7R6 directional mathematical research: independent source-family votes.

The old raw tally treats Binance recent 3m and PREVIOUS anchored 15m
spot taker fractions as separate sign votes. These windows are from the
same venue and may overlap by 0..3 minutes depending on collection lag;
recent 3m is NOT literally a subset of the earlier anchored 15m. Their
statistical independence cannot be inferred from a 2-of-3 vote.
This exploratory policy instead requires flow and separately sourced OKX
book to agree; that can hurt recall, and must be tested prospectively. OI changes participation, not
sign. This does NOT predict future direction or replace the frozen v7R6.
"""
from __future__ import annotations
from btc_demand_v7.demand_change_v2 import advance,feature,state_zero


def binance_window_overlap_minutes(snapshot):
    """Compute overlap of anchored historical 15m and newer live 3m flow.

    The 15m taker fraction is from 15 candles closed at anchor_utc, while
    microflow is from the last three 1m rows closed at vendor_close_ms.
    Returns exact shared duration (0..3 minutes), NOT an independence score.
    """
    from btc_demand_v7.demand_change_v2 import timestamp
    anchor=timestamp(snapshot["anchor_utc"]).timestamp()*1000
    bars=snapshot["microflow_rows"]
    if len(bars)!=6:
        raise ValueError('required six closed 1m rows')
    micro_last=int(bars[-1][6])+1
    micro_first=int(bars[-3][0])
    if micro_last-micro_first!=3*60000:
        raise ValueError('noncontiguous contemporary 3m window')
    overlap=max(0,min(anchor,micro_last)-max(anchor-15*60000,micro_first))
    if overlap>3*60000 or overlap%60000:
        raise ValueError('invalid 3m/15m overlap')
    return int(overlap//60000)


def source_family_consensus(snapshot,side):
    at,vector,readiness=feature(snapshot)
    if vector is None:
        return False
    if side not in ('UP','DOWN'):
        return False
    latest_binance_taker_signed=float(vector[1])
    independent_okx_book_signed=float(vector[2])
    return (latest_binance_taker_signed>0 and independent_okx_book_signed>0
            if side=='UP' else
            latest_binance_taker_signed<0 and independent_okx_book_signed<0)


def paired_mathematical_replay(snapshots):
    """Compare same signed-looking input sequence with separate state chain.

    This callable has NO external signature authority: caller must verify
    inputs independently for any prospective study. Synthetic/backtest data
    cannot establish trading skill or chronological public delivery.
    """
    state=state_zero()
    reports=[]
    for i,snap in enumerate(snapshots):
        old=state
        state,diag=advance(state,snapshots[:i],snap,
                           absolute_consensus_required=False)
        original_alarm=bool(diag['alert'])
        side=diag.get('warning_side')
        ok=source_family_consensus(snap,side) if original_alarm else False
        if original_alarm and not ok:
            # The rejected alarm must NOT spend the one-per-day budget.
            # Keep the same CUSUM and receipt/hash chain for fair replay,
            # but separately carry the last ACCEPTED alarm timestamp only.
            state={**state,'last_alert_utc':old['last_alert_utc'],
                   'last_alert_side':old['last_alert_side']}
            diag={**diag,'status':'RESEARCH_REJECT_NONINDEPENDENT_SOURCES',
                  'alert':False,'warning_side':None}
        else:
            diag={**diag}
        diag['source_independent_consensus_enabled']=True
        diag['source_independent_consensus_passed']=bool(ok)
        diag['old_unfiltered_alarm']=original_alarm
        diag['trading_authority']=False
        diag['calibrated_probability']=False
        reports.append(diag)
    return {'schema':'btc-v7r6-independent-source-directional-research-v1',
            'state':state,'diagnostics':reports,
            'external_signed_observations_verified_by_this_module':False,
            'future_directional_skill_proven':False,
            'trading_authority':False}