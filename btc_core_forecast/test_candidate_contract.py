import unittest
from candidate_contract import admission,REQUIREMENTS,attach_context

class ContractTests(unittest.TestCase):
    def inputs(self):return {k:True for k in ('spot_fresh','R6_verified_and_fresh','macro_required_inputs_verified_and_fresh','actual_operator_quote_current')}
    def test_unit_tests_and_real_receipts_do_not_imply_trade_ready(self):
        out=admission({'tests_passed':1000},self.inputs())
        self.assertFalse(out['trade_decision_allowed']);self.assertIn('predictive_advantage_on_unknown_outcomes',out['missing_requirements'])
    def test_missing_R6_contribution_blocks_full_decision(self):
        evidence={name:True for name in REQUIREMENTS};evidence['R6_contribution_checked']=False
        self.assertFalse(admission(evidence,self.inputs())['full_system_ready'])
    def test_real_spot_is_not_operator_quote(self):
        evidence={name:True for name in REQUIREMENTS};inputs=self.inputs();inputs['actual_operator_quote_current']=False
        self.assertIn('actual_operator_quote_current',admission(evidence,inputs)['missing_requirements'])
    def test_rapid_move_requires_new_assessment(self):
        evidence={name:True for name in REQUIREMENTS};inputs=self.inputs();inputs['rapid_unmodelled_move_observed']=True
        self.assertFalse(admission(evidence,inputs)['full_system_ready'])
    def test_context_cannot_promote_research_output(self):
        evidence={name:True for name in REQUIREMENTS}
        out=attach_context({'full_system_ready':False},evidence,self.inputs(),r6={'available':True})
        self.assertFalse(out['full_system_ready']);self.assertFalse(out['trading_authority'])

if __name__=='__main__':unittest.main()
