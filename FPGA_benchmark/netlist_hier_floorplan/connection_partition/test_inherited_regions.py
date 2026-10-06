"""Parent-region exceptions never waive individual or aggregate resource limits."""
import unittest
from directed_search import Search
from static_regions import RESOURCES,all_rectangles


class InheritedRegionsTests(unittest.TestCase):
    def fixture(self):
        s=Search.__new__(Search)
        s.paths=None
        s.device={f'X{x}Y0':dict(x=x,y=0,slr=0,resources=dict.fromkeys(RESOURCES,100)) for x in range(3)}
        s.rectangles=all_rectangles(s.device);s.lookup={tuple(r['bounds']):r for r in s.rectangles}
        s.modules=[dict(module_id=m,**dict(dict.fromkeys(RESOURCES,0),LUT=60)) for m in ['S00','S01']]
        s.cfg=dict(region_max_area_factor=1,region_max_area_extra_crs=0,
                   inherited_parent_regions={'S00':[0,0,1,0],'S01':[0,0,1,0]})
        s.options={m['module_id']:[s.lookup[(0,0,0,0)]] for m in s.modules}
        s.stats={m['module_id']:dict(minimum_crs=1) for m in s.modules}
        s.keys=list(s.device);s.index={c:i for i,c in enumerate(s.keys)}
        s.density_cache={};s.density_profiles={}
        return s

    def test_exact_parent_added_and_overlap_counted(self):
        s=self.fixture();s.add_inherited_parent_candidates()
        self.assertEqual([len(v) for v in s.options.values()],[2,2])
        plan={m:s.lookup[(0,0,1,0)] for m in s.options}
        self.assertTrue(s.legal(plan))
        # Individually legal at 40%, jointly illegal at 80%.
        for m in s.modules:m['LUT']=80
        s.density_cache.clear()
        self.assertFalse(s.legal(plan))

    def test_exception_does_not_allow_another_equal_area_region(self):
        s=self.fixture();s.add_inherited_parent_candidates()
        self.assertFalse(s.legal({m:s.lookup[(1,0,2,0)] for m in s.options}))

    def test_no_inheritance_preserves_area_limit(self):
        s=self.fixture();s.cfg.pop('inherited_parent_regions');s.add_inherited_parent_candidates()
        self.assertEqual([len(v) for v in s.options.values()],[1,1])
        self.assertFalse(s.legal({m:s.lookup[(0,0,1,0)] for m in s.options}))

    def test_duplicates_not_added(self):
        s=self.fixture();s.add_inherited_parent_candidates();s.add_inherited_parent_candidates()
        self.assertEqual([len(v) for v in s.options.values()],[2,2])

    def test_invalid_parent_rejected(self):
        for mapping in [{'unknown':[0,0,1,0]},{'S00':[0,0,9,0]},{'S00':[0.,0,1,0]}]:
            s=self.fixture();s.cfg['inherited_parent_regions']=mapping
            with self.assertRaises(ValueError):s.add_inherited_parent_candidates()
        s=self.fixture();s.modules[0]['LUT']=150
        with self.assertRaises(ValueError):s.add_inherited_parent_candidates()


if __name__=='__main__':unittest.main()
