import unittest
from directed_model import DirectedModel
from static_regions import RESOURCES

class DirectedTests(unittest.TestCase):
    def setUp(self):
        self.device={f'X0Y{s}':dict(x=0,y=s,slr=s,resources={r:1 for r in RESOURCES}) for s in range(4)}
        self.cfg=dict(slr_distance_weight=4,directed_weight=1,branch_square_weight=32)
    def region(self,*slrs):return dict(bounds=[0,min(slrs),0,max(slrs)],crs=[f'X0Y{s}' for s in slrs])
    def model(self,pairs,n=3,same=0):
        data=dict(module_count=n,pairs=[dict(source=a*9,sink=b*9,weight=w,pins=p) for a,b,w,p in pairs],coverage=dict(same_atom_pins=same),families={})
        return DirectedModel(data,self.device,self.cfg)
    def chosen(self,*slrs):return {f'S{i:02d}':self.region(s) for i,s in enumerate(slrs)}
    def test_single_branch_square(self):
        m=self.model([(0,1,1,1)])
        for span in range(4):
            c=m.components(self.chosen(0,span,0));self.assertAlmostEqual(c['branch_square'],max(0,span-1)**2)
            self.assertAlmostEqual(c['directed_distance'],5*span)
    def test_two_one_boundary_branches_do_not_accumulate(self):
        c=self.model([(0,1,1,1),(1,2,1,1)]).components(self.chosen(0,1,0))
        self.assertEqual(c['branch_square'],0);self.assertEqual(c['directed_slr'],2)
    def test_source_star_changes_with_same_bbox(self):
        m=self.model([(0,1,1,1),(0,2,1,1)])
        center=m.components(self.chosen(1,0,2));end=m.components(self.chosen(0,1,2))
        self.assertEqual(center['branch_square'],0);self.assertEqual(end['branch_square'],1)
        self.assertLess(center['directed_distance'],end['directed_distance'])
    def test_multiplicity_and_control_weight(self):
        c=self.model([(0,1,32,128)]).components(self.chosen(0,2,0),True)
        self.assertEqual(c['branch_square'],32);self.assertEqual(c['raw_far_pins'],128)
        self.assertEqual(c['branch_square_term'],1024)
    def test_expected_square_not_square_of_mean(self):
        m=self.model([(0,1,1,1)]);chosen=self.chosen(0,0,0);chosen['S01']=self.region(0,1,2)
        c=m.components(chosen);self.assertAlmostEqual(c['directed_slr'],1);self.assertAlmostEqual(c['branch_square'],1/3)
    def test_internal_distinct_atoms_nonzero_same_atom_zero(self):
        m=self.model([(0,0,1,1)],n=1,same=5);chosen={'S00':self.region(0,1,2)}
        c=m.components(chosen,True);self.assertGreater(c['directed_distance'],0)
        self.assertAlmostEqual(m.internal_cost(0,chosen['S00']),c['directed_term']+c['branch_square_term'])
        self.assertAlmostEqual(sum(c['raw_boundary_histogram'].values()),6)
    def test_explicit_pairs_match_matrix(self):
        m=self.model([(0,1,3.25,13)]);chosen=self.chosen(0,1,0)
        chosen['S00']=self.region(0,1);chosen['S01']=self.region(1,2,3)
        c=m.components(chosen)
        expected=sum(3.25*(5*abs(a-b)+32*max(0,abs(a-b)-1)**2)/6 for a in (0,1) for b in (1,2,3))
        self.assertAlmostEqual(c['directed_term']+c['branch_square_term'],expected)
    def test_parameter_weights_propagate(self):
        m=self.model([(0,1,1,1)]);m.cfg=dict(slr_distance_weight=2,directed_weight=3,branch_square_weight=7)
        c=m.components(self.chosen(0,2,0));self.assertEqual(c['directed_term'],18);self.assertEqual(c['branch_square_term'],7)

    def test_named_physical_groups_preserve_slot_order(self):
        old=self.model([(0,1,3.25,13),(2,0,1,4)])
        names=['S00','S00G01','S09']
        data=dict(old.data,module_ids=names)
        family=dict(nets=2,sink_pins=17,same_atom_pins=0,pairs=data['pairs'])
        old.data['families']={'test':family};data['families']={'test':family}
        named=DirectedModel(data,self.device,self.cfg)
        reference=self.chosen(2,1,3)
        plan={mid:reference[f'S{i:02d}'] for i,mid in enumerate(names)}
        self.assertEqual(named.components(plan,True),old.components(reference,True))
        self.assertEqual(named.family_audit(plan),old.family_audit(reference))

    def test_invalid_named_groups_fail(self):
        old=self.model([(0,1,1,1)])
        for names in [['S00'],['S00','S00','S01']]:
            with self.assertRaises(ValueError):
                DirectedModel(dict(old.data,module_ids=names),self.device,self.cfg)

if __name__=='__main__':unittest.main()
