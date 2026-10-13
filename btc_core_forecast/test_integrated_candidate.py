import unittest
from unittest.mock import patch
import numpy as np
import integrated_candidate as c
from factor_integration import FEATURE_NAMES

class FitContractTests(unittest.TestCase):
    def arrays(self):return {'x':np.zeros((1,len(FEATURE_NAMES)))}
    def test_missing_factor_blocks_before_fit(self):
        with patch.object(c.direction,'fit',side_effect=AssertionError('must not fit')) as fit:
            with self.assertRaisesRegex(ValueError,'unavailable'):c.fit_verified(self.arrays(),[{'eligible_for_research_matrix':False}],[0],[0])
            fit.assert_not_called()
    def test_unpinned_macro_cannot_be_marked_verified_training(self):
        row={'eligible_for_research_matrix':True,'features':[0.]*len(FEATURE_NAMES),'feature_names':FEATURE_NAMES,'macro_quotes':{'immutable_collector_source_proven':False}}
        with self.assertRaisesRegex(ValueError,'unpinned'):c.fit_verified(self.arrays(),[row],[0],[0])
    def test_spot_only_model_cannot_be_called_as_integrated(self):
        with self.assertRaisesRegex(ValueError,'fixed integrated'):c.paths({'volatility':{}},np.zeros(len(FEATURE_NAMES)),.001)
    def full_row(self):
        return {'eligible_for_research_matrix':True,'features':[0.]*len(FEATURE_NAMES),'feature_names':FEATURE_NAMES,
            'macro_quotes':{'immutable_collector_source_proven':True},'anchor_utc':'2026-09-29T00:00:00+00:00','reference_spot':100.,'past_sigma':.01}
    def full_arrays(self):
        return {'x':np.zeros((1,len(FEATURE_NAMES))),'close':np.ones((1,72)),'high':np.ones((1,72)),'low':np.zeros((1,72)),
            'anchors':np.array([1790640000000]),'spot':np.array([100.]),'scales':np.array([.01])}
    def test_shifted_target_anchor_blocks_before_fit(self):
        a=self.full_arrays();a['anchors']+=3600000
        with patch.object(c.direction,'fit') as fit:
            with self.assertRaisesRegex(ValueError,'target anchor'):c.fit_verified(a,[self.full_row()],[0],[0])
            fit.assert_not_called()
    def test_minimum_split_cannot_be_lowered_to_make_tiny_fit_pass(self):
        with patch.object(c.direction,'fit') as fit:
            with self.assertRaisesRegex(ValueError,'minimum 240'):c.fit_verified(self.full_arrays(),[self.full_row()],[0],[0])
            fit.assert_not_called()

if __name__=='__main__':unittest.main()
