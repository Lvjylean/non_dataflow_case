"""Regression cases for spatial simplification, directions, and unchanged risk."""
import copy
import itertools
import unittest

from boundary_hyper import TYPES, lift
from boundary_directed import BoundaryDirectedModel, SCHEMA, independent_components, attach
from directed_model import DirectedModel
from test_boundary_hyper import graph, device, region, slot

CFG=dict(directed_distance_model=SCHEMA,directed_weight=1.,slr_distance_weight=8.,branch_square_weight=32.)


def spatial(kinds,nets,labels):
    return lift(graph(kinds,nets),labels,max(labels)+1,with_directed=True)[2]


def pairs(data):
    return {(e['source'],e['sink']):e['weight'] for e in data['pairs']}


class BoundaryDirectedTests(unittest.TestCase):
    def test_internal_ff_chain_zero_and_cross_boundary_kept(self):
        self.assertFalse(spatial(['FF','LUT','FF'],[(0,[1]),(1,[2])],[0,0,0])['pairs'])
        self.assertEqual(pairs(spatial(['FF','LUT','FF'],[(0,[1]),(1,[2])],[0,0,1])),
                         {(slot(0,'FF'),slot(1,'FF')):1.})

    def test_hard_chain_stops_at_first_hard_even_through_ff_feedback(self):
        data=spatial(['BRAM18','FF','FF','DSP','URAM'],
            [(0,[1]),(1,[2]),(2,[1,3]),(3,[4])],[0]*5)
        self.assertEqual(pairs(data),{(slot(0,'BRAM18'),slot(0,'DSP')):1.,
                                     (slot(0,'DSP'),slot(0,'URAM')):1.})

    def test_all_hard_endpoint_types_and_same_resource_distinct_atoms(self):
        for a,b in itertools.product(['DSP','BRAM18','URAM'],repeat=2):
            self.assertEqual(pairs(spatial([a,'LUT',b],[(0,[1]),(1,[2])],[0]*3)),
                             {(slot(0,a),slot(0,b)):1.})

    def test_ff_is_not_transparent_across_module_boundary(self):
        self.assertEqual(pairs(spatial(['BRAM18','FF','DSP'],[(0,[1]),(1,[2])],[0,1,1])),
                         {(slot(0,'BRAM18'),slot(1,'FF')):1.})
        self.assertEqual(pairs(spatial(['BRAM18','FF','DSP'],[(0,[1]),(1,[2])],[0,0,1])),
                         {(slot(0,'FF'),slot(1,'DSP')):1.})

    def test_direction_fanout_and_reconvergence(self):
        data=spatial(['BRAM18','LUT','LUT','DSP','DSP'],
            [('n0',0,(1,2,2),4),('n1',1,(3,4),4),('n2',2,(3,3),4),
             ('another_bit',0,(1,2),1)],[0]*5)
        self.assertEqual(pairs(data),{(slot(0,'BRAM18'),slot(0,'DSP')):2.5})
        self.assertEqual(data['audit']['directed_endpoint_branches'],4)

    def test_only_relevant_anchors_absorb_combinational_locations(self):
        data=spatial(['BRAM18','LUT','DSP','FF'],[(0,[1]),(1,[2])],[0,1,2,1])
        self.assertEqual(pairs(data),{(slot(0,'BRAM18'),slot(2,'DSP')):1.,
                                     (slot(0,'BRAM18'),slot(1,'COMB_CENTER')):1.})
        data=spatial(['BRAM18','LUT','DSP'],[(0,[1]),(1,[2])],[0,0,1])
        self.assertEqual(pairs(data),{(slot(0,'BRAM18'),slot(1,'DSP')):1.})

    def test_proxy_is_a_deterministic_fractional_mean(self):
        data=spatial(['LUT','LUT'],[(0,[1])],[0,1]);dev=device()
        cfg=dict(CFG);model=BoundaryDirectedModel(data,dev,cfg,['S00','S01'])
        p={'S00':region(dev,0,1),'S01':region(dev,0,1)}
        self.assertAlmostEqual(model.components(p)['directed_distance'],0.)
        p['S01']=region(dev,1,2)
        # Means x=.5/1.5, SLR=0/.5: exact fractional geometry, not rounded CRs.
        self.assertAlmostEqual(model.components(p)['directed_distance'],5.)

    def test_full_support_enumeration_and_internal_cost(self):
        data=spatial(['BRAM18','FF','DSP','LUT','FF'],[(0,[1]),(1,[2]),(2,[3]),(3,[4])],[0,0,0,1,2])
        dev=device();ids=['S00','S01','S02'];p={m:region(dev,0,1,2,3) for m in ids}
        model=BoundaryDirectedModel(data,dev,CFG,ids)
        fast=model.components(p);slow=independent_components(data,p,dev,CFG,ids)
        for key,value in slow.items():self.assertAlmostEqual(fast[key],value)
        self.assertAlmostEqual(model.internal_cost(0,p['S00']),fast['directed_internal_distance'])

    def test_raw_branch_square_and_histogram_are_unchanged(self):
        dev=device();raw=dict(module_count=2,pairs=[dict(source=1,sink=10,weight=1,pins=1)],
            coverage=dict(same_atom_pins=0),families={})
        p={'S00':region(dev,0,1),'S01':region(dev,2,3)}
        old=DirectedModel(raw,dev,{k:v for k,v in CFG.items() if k!='directed_distance_model'}).components(p,True)
        newdata=dict(raw,spatial=spatial(['FF','FF'],[(0,[1])],[0,1]))
        new=DirectedModel(newdata,dev,CFG).components(p,True)
        for k in ('branch_square','branch_square_term','raw_far_pins','raw_branch_boundaries','raw_boundary_histogram'):
            self.assertEqual(old[k],new[k])

    def test_missing_cache_and_unsupported_model_fail(self):
        with self.assertRaisesRegex(ValueError,'rebuild'):attach({},object(),CFG)
        with self.assertRaisesRegex(ValueError,'Unknown'):attach({},object(),dict(directed_distance_model='bad'))

    def test_lutmem_and_unknown_source_are_not_invented_boundaries(self):
        self.assertFalse(spatial(['BRAM18','LUTMEM','DSP'],[(0,[1]),(1,[2])],[0]*3)['pairs'])
        data=spatial(['LUT','FF'],[('port','PORT:in',(0,),4),('out',0,(1,),4)],[0,1])
        self.assertFalse(data['pairs'])
        self.assertGreater(data['audit']['directed_unknown_source_roots'],0)

    def test_spatial_lift_preserves_hypernet_and_original_netlist(self):
        d=graph(['BRAM18','LUT','FF','DSP'],[(0,[1]),(1,[2,3])]);old=copy.deepcopy(d)
        a=lift(d,[0,1,2,2],3);b=lift(d,[0,1,2,2],3,with_directed=True)
        self.assertEqual(a[0],b[0]);self.assertEqual(d,old)


if __name__=='__main__':unittest.main()
