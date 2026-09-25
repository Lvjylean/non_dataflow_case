"""Independent small cases for raw timing costs, correlation and feedback."""
import itertools
import unittest

import numpy as np

from balanced_physical import NetModel
from static_regions import RESOURCES
from timing_model import crossing_distribution,positive_square,CriticalModel,criticality


CFG=dict(slr_distance_weight=4.,critical_distance_weight=10.,path_square_weight=100.,
         criticality_floor=1.,criticality_ceiling=10.,criticality_window_ns=.5)


def device():
    return {f'X0Y{y}':dict(x=0,y=y,slr=y//2,resources={r:(10 if r in ('LUT','FF','BRAM18') else 0) for r in RESOURCES}) for y in range(6)}


def region(d,ys):
    crs=[f'X0Y{y}' for y in ys]
    return dict(crs=crs,bounds=[0,min(ys),0,max(ys)],slrs=sorted({d[c]['slr'] for c in crs}),
                capacity={r:sum(d[c]['resources'][r] for c in crs) for r in RESOURCES})


class TimingTests(unittest.TestCase):
    def test_cross_two_boundaries(self):
        h=crossing_distribution([[0,0,1],[1,0,0]])
        self.assertEqual(h,{2:1.});self.assertEqual(positive_square(h),1.)

    def test_round_trip_is_cumulative(self):
        h=crossing_distribution([[0,0,1],[1,0,0],[0,0,1]])
        self.assertEqual(h,{4:1.});self.assertEqual(positive_square(h),9.)

    def test_zero_and_one_are_free(self):
        self.assertEqual(positive_square({0:.4,1:.6}),0)

    def test_expectation_of_square_not_square_of_expectation(self):
        h=crossing_distribution([[1,0,0],[.5,0,.5]])
        self.assertEqual(positive_square(h),.5)
        self.assertNotEqual(positive_square(h),max(0,sum(n*p for n,p in h.items())-1)**2)

    def test_dynamic_distribution_against_full_enumeration(self):
        probabilities=[[.2,.3,.5],[.7,.2,.1],[.4,.4,.2],[.1,.2,.7]]
        expected={}
        for locs in itertools.product(range(3),repeat=4):
            n=sum(abs(a-b) for a,b in zip(locs,locs[1:]))
            p=np.prod([row[i] for row,i in zip(probabilities,locs)])
            expected[n]=expected.get(n,0)+p
        actual=crossing_distribution(probabilities)
        for n,v in expected.items():self.assertAlmostEqual(actual[n],v)

    def test_same_atom_return_retains_correlation(self):
        probs=[[.5,0,.5],[0,1,0],[.5,0,.5]]
        self.assertEqual(crossing_distribution(probs,[0,1,0]),{2:1.})

    def test_same_atom_twice_cannot_move(self):
        self.assertEqual(crossing_distribution([[.5,.5],[.5,.5]],[0,0]),{0:1.})

    def test_criticality_clip_and_scale(self):
        self.assertEqual(criticality(-.1,CFG),10)
        self.assertEqual(criticality(.5,CFG),1)
        self.assertAlmostEqual(criticality(.032,CFG),9.424)

    def test_configured_slr_weight_reaches_base_components(self):
        d=device();model=NetModel(dict(atom_resources=[dict(LUT=1),dict(LUT=1)],edges=[((0,1),4)]),[0,1],2,d)
        chosen={'P00':region(d,[0]),'P01':region(d,[4])}
        self.assertEqual(model.components(chosen,4)['physical_cost'],12)
        self.assertEqual(model.components(chosen,8)['physical_cost'],20)

    def test_driver_movement_has_value_when_hyperedge_span_stays(self):
        d=device();f=dict(nodes={'0':dict(module='S00',resource='BRAM18'),
            '1':dict(module='S01',resource='LUT'),'2':dict(module='S02',resource='LUT')},
            connections=[dict(source=0,sink=1,criticality=10),dict(source=0,sink=2,criticality=10)],
            paths=[dict(atoms=[0,1],criticality=10)],broadcast=dict(source=0,sinks=[1,2]))
        model=CriticalModel(f,d,CFG)
        a={'S00':region(d,[5]),'S01':region(d,[0]),'S02':region(d,[4])}
        b=dict(a,S00=region(d,[2]))
        self.assertLess(model.components(b)['critical_connection_distance'],model.components(a)['critical_connection_distance'])
        self.assertEqual(model.components(a)['path_square_term'],1000)
        self.assertEqual(model.components(b)['path_square_term'],0)
        self.assertEqual(model.broadcast(a)['expected_far_sink_pins'],1)
        self.assertEqual(model.broadcast(b)['expected_far_sink_pins'],0)

    def test_geometry_gives_gradual_gain_before_die_crossing_changes(self):
        d=device();f=dict(nodes={'0':dict(module='S00',resource='BRAM18'),'1':dict(module='S01',resource='LUT')},
            connections=[dict(source=0,sink=1,criticality=10)],paths=[dict(atoms=[0,1],criticality=10)])
        model=CriticalModel(f,d,CFG)
        a=model.components({'S00':region(d,[5]),'S01':region(d,[0])})
        b=model.components({'S00':region(d,[4]),'S01':region(d,[1])})
        self.assertEqual(a['path_square_term'],b['path_square_term'])
        self.assertLess(b['critical_connection_term'],a['critical_connection_term'])


if __name__=='__main__':unittest.main()
