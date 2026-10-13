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

if __name__=='__main__':unittest.main()
