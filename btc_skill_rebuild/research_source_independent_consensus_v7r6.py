"""v7R6 directional mathematical research: independent source-family votes.

The old raw tally treats Binance 3m and Binance 15m taker fractions as two
independent sign votes, even though 3m is a subset of 15m. This exploratory
alternative uses only recent signed Binance microflow AND independently
received OKX book for directional agreement. OI changes participation, not
sign. This does NOT predict future direction or replace the frozen v7R6.
"""
from __future__ import annotations
from btc_demand_v7.demand_change_v2 import advance,feature,state_zero


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