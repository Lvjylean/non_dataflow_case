import unittest
from static_regions import RESOURCES, all_rectangles, candidates, family_windows, overlap_audit


def device():
    return {f'X{i}Y0':dict(x=i,y=0,slr=i,resources={r:(8 if r=='URAM' else 100) for r in RESOURCES})
            for i in range(2)}


class StaticRegionTests(unittest.TestCase):
    def test_family_uses_contiguous_sufficient_capacity_windows(self):
        d={f'X{i}Y0':dict(x=i,y=0,slr=i,resources={r:(8 if r=='URAM' else 100) for r in RESOURCES})
           for i in range(3)}
        modules=[dict(module_id='A',cells=5,URAM=8,baseline_parent_cells={'P':5}),
                 dict(module_id='B',cells=5,URAM=8,baseline_parent_cells={'P':5})]
        families=family_windows(modules,d)
        self.assertEqual(families['P']['windows'],[[0,1],[1,2]])
        self.assertNotIn([0,2],families['P']['windows'])

    def test_resource_heavy_parent_needs_two_slrs_but_children_need_one(self):
        regions=all_rectangles(device())
        _,large=candidates({'URAM':16},regions)
        _,child=candidates({'URAM':8},regions)
        self.assertEqual(large['min_slrs'],2)
        self.assertEqual(child['min_slrs'],1)

    def test_complementary_resources_can_share_region(self):
        d=device();region=next(r for r in all_rectangles(d) if r['area']==1)
        modules=[dict(module_id='A',URAM=8,LUT=5),dict(module_id='B',LUT=60)]
        audit=overlap_audit(modules,{'A':region,'B':region},d)
        self.assertTrue(audit['valid'])
        self.assertEqual(audit['overlapping_crs'],1)
        self.assertAlmostEqual(audit['maximum_utilization']['LUT'],.65)

    def test_individual_fit_does_not_imply_overlap_fit(self):
        d=device();region=next(r for r in all_rectangles(d) if r['area']==2)
        modules=[dict(module_id='A',URAM=10),dict(module_id='B',URAM=10)]
        audit=overlap_audit(modules,{'A':region,'B':region},d)
        self.assertFalse(audit['valid'])
        self.assertAlmostEqual(audit['maximum_utilization']['URAM'],1.25)


if __name__=='__main__': unittest.main()
