"""One status for two independent 4h tail warnings and uncalibrated regime."""
import math
from datetime import timedelta
from upstream_rules import decide as upside_decide


def decide(up, regime, down, *, anchor):
    base = upside_decide(up, regime, anchor=anchor)
    slot = base['slot']
    result = {**base, 'directional_down_tail_alert': None,
              'downside_rank_30d': None, 'downside_candidate_estimate_unproven': None,
              'downside_head_status': 'UNAVAILABLE', 'trading_authority': False}
    if down is None:
        result['status'] = ('UPSIDE_TAIL_RISK_DOWN_HEAD_UNAVAILABLE' if base['directional_up_tail_alert']
                            else 'DOWN_HEAD_UNAVAILABLE_NO_DIRECTIONAL_CONCLUSION')
        result['reason'] = 'no timely signed downside source; no downside conclusion'
        return result
    if down.get('type') != 'DIRECTIONAL_4H_DOWNSIDE_ALERT_ISSUED' or down.get('slot') != slot:
        raise ValueError('downside event type or slot mismatch')
    if down.get('idempotency_key') != 'down-alert:' + slot or down.get('due_utc') != base['due_utc']:
        raise ValueError('downside key or due mismatch')
    price = float(down['reference_price'])
    if not math.isfinite(price) or abs(price-base['reference_price']) > .01:
        raise ValueError('downside reference price mismatch')
    output = down['output']
    rank = float(output['rank_30d'])
    estimate = float(output['candidate_estimate'])
    cutoff = float(output['cutoff_rank'])
    if (not all(math.isfinite(v) for v in (rank,estimate,cutoff)) or
            not 0<=rank<=1 or not 0<=estimate<=1 or cutoff != .8 or
            output.get('past_scores_count') != 720):
        raise ValueError('invalid downside numbers')
    alert=output['alert']
    if type(alert) is not bool or alert != (rank >= cutoff):
        raise ValueError('downside alert/rank inconsistency')
    result.update(directional_down_tail_alert=alert, downside_rank_30d=rank,
                  downside_candidate_estimate_unproven=estimate,
                  downside_head_status='SHADOW_PROSPECTIVE_UNPROVEN')
    if alert and base['directional_up_tail_alert']:
        status='BIDIRECTIONAL_TAIL_RISK_CONFLICT'
    elif alert and regime is None:
        status='DOWNSIDE_TAIL_RISK_REGIME_UNAVAILABLE'
    elif alert and base['regime_4h_top_shadow_class']=='downside' and base['regime_state'] in ('DOWN_TRANSITION','DOWN_CONTINUATION'):
        status='DOWNSIDE_TAIL_RISK_CONCORDANT'
    elif alert:
        status='DOWNSIDE_TAIL_RISK_WITH_REGIME_DISAGREEMENT'
    else:
        status=base['status']
    result['status']=status
    if alert:
        result['action_status']='WATCH_ONLY_NO_TRADE_AUTHORITY'
        result['reason']='independent downside tail warning, prospective unproven; no trade authority'
    return result
