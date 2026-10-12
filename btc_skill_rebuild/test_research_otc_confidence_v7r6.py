"""Adversarial invariants of BTC v7R6 OTC confidence mathematics.

Synthetic unit tests are not financial accuracy evidence.
"""
import unittest
from datetime import datetime,timedelta,timezone
from btc_skill_rebuild.research_otc_confidence_v7r6 import (
    MaturedDay,bound_wait_utility,worst_case_wait_advantage_btc)

UTC=timezone.utc
NOW=datetime(2026,11,3,15,0,tzinfo=UTC)

def samples(residual=-.002,train_prediction=.005,n=20):
    result=[]
    for days in range(n,0,-1):
        t=NOW-timedelta(days=days)
        result.append(MaturedDay(t,t+timedelta(minutes=8),
                        t+timedelta(minutes=125),
                        train_prediction,train_prediction+residual))
    return result

class TailVetoTests(unittest.TestCase):
    def test_both_future_operator_markup_extremes_are_included(self):
        gain=worst_case_wait_advantage_btc(83000.,82500.)
        self.assertAlmostEqual(gain,147600/(82500+400)-147600/(83000+300))
        self.assertGreater(gain,0)
        self.assertLess(worst_case_wait_advantage_btc(83000.,82950.),0)
        with self.assertRaises(ValueError):
            worst_case_wait_advantage_btc(0.,83000.)

    def test_no_confirmation_when_even_one_calendar_day_is_missing(self):
        r=bound_wait_utility(NOW,.005,samples(n=19))
        self.assertEqual(r["calibration_days_available"],19)
        self.assertEqual(r["decision"],"INSUFFICIENT_MATURED_CALIBRATION")
        self.assertEqual(len(r["missing_precommitted_UTC_days"]),1)
        self.assertFalse(r["mathematical_wait_candidate"])
        with self.assertRaises(ValueError):
            bound_wait_utility(NOW,.005,samples()+samples()[:1])

    def test_adverse_forecast_residual_does_not_disappear(self):
        r=bound_wait_utility(NOW,.005,samples(residual=-.007))
        self.assertAlmostEqual(r["forecast_lower_bound_btc"],-.002)
        self.assertEqual(r["residual_quantile_rank_1based"],3)
        self.assertEqual(r["decision"],"ABSTAIN_WAIT")
        self.assertFalse(r["trading_authority"])
        r=bound_wait_utility(NOW,.02,samples(residual=-.007))
        self.assertTrue(r["mathematical_wait_candidate"])
        self.assertFalse(r["prospective_trade_profit_proven"])

    def test_one_severe_loss_not_hidden_by_optimistic_percentile(self):
        a=samples(residual=.002)
        s=a[2]
        a[2]=MaturedDay(s.issued_utc,s.publicly_issued_utc,
                         s.outcome_matured_utc,s.predicted_nominal_wait_gain_btc,
                         s.predicted_nominal_wait_gain_btc-.02)
        result=bound_wait_utility(NOW,.002,a)
        self.assertGreater(result["adverse_residual_lower_quantile_btc"],0)
        self.assertLess(result["adverse_tail_average_residual_btc"],0)
        self.assertLess(result["forecast_lower_bound_btc"],0)
        self.assertFalse(result["mathematical_wait_candidate"])

    def test_current_and_future_outcome_not_allowed_into_calibration(self):
        old=bound_wait_utility(NOW,.004,samples())
        t=NOW
        tampered=samples()+[MaturedDay(t,t+timedelta(minutes=8),
                          t+timedelta(minutes=125),-.01,100.)]
        new=bound_wait_utility(NOW,.004,tampered)
        self.assertEqual(old["forecast_lower_bound_btc"],new["forecast_lower_bound_btc"])

    def test_untimely_predictions_or_immature_outcomes_rejected(self):
        a=samples()
        s=a[2]
        a[2]=MaturedDay(s.issued_utc,s.issued_utc+timedelta(minutes=61),
                         s.outcome_matured_utc,s.predicted_nominal_wait_gain_btc,
                         s.worst_realized_wait_gain_btc)
        with self.assertRaises(ValueError):
            bound_wait_utility(NOW,.01,a)
        a=samples()
        s=a[0]
        a[0]=MaturedDay(s.issued_utc,s.publicly_issued_utc,
                         NOW+timedelta(minutes=1),s.predicted_nominal_wait_gain_btc,
                         s.worst_realized_wait_gain_btc)
        with self.assertRaises(ValueError):
            bound_wait_utility(NOW,.01,a)

    def test_unknown_provenance_fails_closed(self):
        a=samples()
        s=a[-1]
        a[-1]=MaturedDay(s.issued_utc,s.publicly_issued_utc,s.outcome_matured_utc,
                         s.predicted_nominal_wait_gain_btc,s.worst_realized_wait_gain_btc,
                         "already_proven_profitable")
        with self.assertRaises(ValueError):
            bound_wait_utility(NOW,.01,a)

if __name__=="__main__":
    unittest.main()
