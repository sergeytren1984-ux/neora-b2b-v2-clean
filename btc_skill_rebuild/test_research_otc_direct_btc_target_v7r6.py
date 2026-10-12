"""Causal mathematical tests for direct UTC t+60/t+120 OTC BTC target."""
import math,unittest
from unittest.mock import patch
from datetime import datetime,timedelta,timezone
from btc_skill_rebuild.research_otc_direct_btc_target_v7r6 import (
    btc_opportunity_gain,forecast_markup_uncertainty_margin,
    decide_from_expected_btc_gain,daily_score,MARKUP_USDT_PER_BTC)
from btc_skill_rebuild.research_otc_execution_utility_v7r6 import CAPITAL_USDT
UTC=timezone.utc
START=datetime(2026,9,14,15,0,tzinfo=UTC)

class DirectOTCMathTests(unittest.TestCase):
    def test_real_target_is_btc_not_unexecuted_spot_price(self):
        self.assertEqual(btc_opportunity_gain(83000,83000),0.)
        gain=btc_opportunity_gain(83000,82000)
        self.assertGreater(gain,0.)
        self.assertAlmostEqual(gain,CAPITAL_USDT/(82000+350)-CAPITAL_USDT/(83000+350))
        self.assertLess(btc_opportunity_gain(82000,83000),0.)
        with self.assertRaises(ValueError):btc_opportunity_gain(83000,0)

    def test_action_uses_only_issue_time_price_and_spread_uncertainty(self):
        margin=forecast_markup_uncertainty_margin(83000)
        self.assertAlmostEqual(margin,CAPITAL_USDT*100/(83000+350)**2)
        self.assertEqual(decide_from_expected_btc_gain(margin*.8,83000),"BUY_NOW")
        self.assertEqual(decide_from_expected_btc_gain(margin*1.1,83000),"WAIT_60")
        with self.assertRaises(ValueError):decide_from_expected_btc_gain(float("nan"),83000)

    def example(self,deltas):
        result=[]
        for j,prices in enumerate(deltas):
            t=START+timedelta(days=j)
            known,spot60,spot120=prices
            delta=btc_opportunity_gain(spot60,spot120)
            result.append((int(t.timestamp()*1000),(0.,)*17,delta,known,spot60,spot120))
        return result

    def test_negative_wait_opportunity_is_a_real_loss(self):
        sample=self.example([(83000.,82000.,83000.)]*7)
        with patch("btc_skill_rebuild.research_otc_direct_btc_target_v7r6.predict",
                   return_value=.01):
            x=daily_score(sample,None,1.)
        self.assertEqual(x["n_predeclared_daily_decisions"],7)
        self.assertEqual(x["historical_wait_decisions"],7)
        self.assertLess(x["full_budget_spot_proxy_mean_incremental_btc_vs_buy_now"],0.)
        self.assertEqual(x["robust_wait_signals_correct"],0)
        self.assertEqual(x["robust_wait_signals_wrong"],7)
        self.assertGreater(x["oracle_regret_btc_EX_POST_ONLY"],0.)
        self.assertEqual(x["oracle_number_wait_winning_days_EX_POST_ONLY"],0)
        with patch("btc_skill_rebuild.research_otc_direct_btc_target_v7r6.predict",
                   return_value=.01):
            abstain=daily_score(sample,None,0.)
        self.assertEqual(abstain["full_budget_spot_proxy_mean_incremental_btc_vs_buy_now"],0.)
        self.assertEqual(abstain["historical_wait_decisions"],0)

    def test_one_daily_portfolio_opportunity_no_correlated_reuse(self):
        sample=self.example([(83000.,83500.,83000.)]*7)
        sample.append(sample[0])
        with self.assertRaises(ValueError):daily_score(sample,None,0.)
        sample[0]=sample[1] # duplicates two slots on same day
        with self.assertRaises(ValueError):daily_score(sample,None,0.)

if __name__=="__main__":unittest.main()
