"""Adversarial OTC forecast mathematics, no source collection or automation."""
import unittest
from datetime import datetime,timedelta,timezone
from btc_skill_rebuild.research_otc_execution_utility_v7r6 import (
    Quote,Prediction,CAPITAL_USDT,paired_economic_outcome,
    markup_robust_direction,independent_day_economic_evidence)
UTC=timezone.utc
T=datetime(2026,10,13,8,0,tzinfo=UTC)
FROZEN_SHA="a"*64

class OTCDelayedUtilityTests(unittest.TestCase):
    def quotes(self,p60=83000.,p120=82500.,status="firm_available",
               origin="operator",predicted_wait=0.001):
        signal=Prediction(T,T+timedelta(minutes=8),predicted_wait,FROZEN_SHA)
        q60=Quote(T+timedelta(minutes=60),p60+350,status,origin,CAPITAL_USDT)
        q120=Quote(T+timedelta(minutes=120),p120+350,status,origin,CAPITAL_USDT)
        return signal,q60,q120

    def outcome(self,*args,**kwargs):
        return paired_economic_outcome(*self.quotes(*args,**kwargs))

    def test_compares_delayed_all_in_asks_not_publication_spot(self):
        r=self.outcome()
        self.assertTrue(r["identified"])
        self.assertEqual(r["forecast_action"],"WAIT_60")
        self.assertEqual(r["realized_best_action_conditional_on_full_fills"],"WAIT_60")
        self.assertAlmostEqual(r["wait_minus_now_btc"],
             CAPITAL_USDT/(82500+350)-CAPITAL_USDT/(83000+350))
        self.assertGreater(r["incremental_btc_vs_buy_now"],0)
        self.assertFalse(r["economic_proven"])
        self.assertFalse(r["trading_authority"])

    def test_losing_waits_count_as_negative_not_discarded(self):
        r=self.outcome(p60=82000.,p120=83000.)
        self.assertLess(r["incremental_btc_vs_buy_now"],0.)
        self.assertFalse(r["forecast_action_correct"])
        self.assertEqual(r["realized_best_action_conditional_on_full_fills"],"BUY_NOW")
        r=self.outcome(p60=82000.,p120=83000.,predicted_wait=-.01)
        self.assertEqual(r["incremental_btc_vs_buy_now"],0.)

    def test_invalid_quotes_and_off_schedule_not_silent_success(self):
        for status in ("rejected","missing","indicative"):
            self.assertFalse(self.outcome(status=status)["identified"])
        sig,q60,q120=self.quotes()
        poor=Quote(q60.time_utc,q60.ask_usdt_per_btc,"firm_available","operator",
                   CAPITAL_USDT-1)
        self.assertFalse(paired_economic_outcome(sig,poor,q120)["identified"])
        late=Quote(T+timedelta(minutes=90),q60.ask_usdt_per_btc,
                   "firm_available","operator",CAPITAL_USDT)
        self.assertFalse(paired_economic_outcome(sig,late,q120)["identified"])
        with self.assertRaises(ValueError):
            paired_economic_outcome(Prediction(T,T+timedelta(minutes=61),
                                                .01,FROZEN_SHA),q60,q120)
        with self.assertRaises(ValueError):
            paired_economic_outcome(Prediction(T,T+timedelta(minutes=3),
                                                .01,"not-a-sha"),q60,q120)

    def test_unknown_spreads_prevent_unjustified_action_label(self):
        self.assertEqual(markup_robust_direction(83500,83200),
                         "WAIT_60_ROBUSTLY_CHEAPER")
        self.assertEqual(markup_robust_direction(83100,83500),
                         "BUY_NOW_ROBUSTLY_CHEAPER")
        self.assertEqual(markup_robust_direction(83100,83060),
                         "NOT_ROBUST_TO_OTC_MARKUP")
        self.assertEqual(markup_robust_direction(83100,83100),
                         "NOT_ROBUST_TO_OTC_MARKUP")

    def test_day_blocks_and_unverifiable_counterfactual_cannot_grant_access(self):
        first=self.outcome()
        with self.assertRaises(ValueError):
            independent_day_economic_evidence([first,first])
        rows=[]
        for i in range(20):
            ti=T+timedelta(days=i)
            sig=Prediction(ti,ti+timedelta(minutes=8),.01,FROZEN_SHA)
            q60=Quote(ti+timedelta(minutes=60),83350,"firm_available",
                      "operator",CAPITAL_USDT)
            q120=Quote(ti+timedelta(minutes=120),82850,"firm_available",
                       "operator",CAPITAL_USDT)
            rows.append(paired_economic_outcome(sig,q60,q120))
        agg=independent_day_economic_evidence(rows)
        self.assertEqual(agg["calendar_days"],20)
        self.assertTrue(agg["conditional_quote_lower95_positive"])
        self.assertFalse(agg["verified_positive_economic_edge"])
        self.assertFalse(agg["trading_authority"])
        rows[0]={"slot":rows[0]["slot"],"identified":False}
        self.assertFalse(independent_day_economic_evidence(rows)["conditional_quote_lower95_positive"])

    def test_spot_proxy_never_establishes_operator_execution(self):
        r=self.outcome(origin="spot_proxy")
        self.assertTrue(r["identified"])
        self.assertEqual(r["provenance"],"spot_or_mixed_proxy")
        self.assertFalse(independent_day_economic_evidence([r])["verified_positive_economic_edge"])

if __name__=="__main__":
    unittest.main()
