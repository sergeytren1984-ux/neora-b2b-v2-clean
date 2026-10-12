import unittest
from btc_skill_rebuild.research_adaptive_climatology_v7r6 import (
    CausalClimatology, independent_due_climatology_population
)

class IndependentGridTest(unittest.TestCase):
    def test_daily_grid_does_not_count_overlapping_slots(self):
        base=1700006400000
        population=[(base+i*900000,base+i*900000+86400000,(0.0,),i%3)
                    for i in range(31*96)]
        independent=independent_due_climatology_population(population,288)
        self.assertEqual(len(independent),31)
        self.assertTrue(all(t%86400000==0 for t,_,_,_ in independent))
        issue=population[2000][0]
        self.assertNotEqual(CausalClimatology(population).probability(issue,7),
                            CausalClimatology(independent).probability(issue,7))
        for bad in (0,-1,1.5,True):
            with self.assertRaises(ValueError):
                independent_due_climatology_population(population,bad)

if __name__=="__main__":
    unittest.main()
