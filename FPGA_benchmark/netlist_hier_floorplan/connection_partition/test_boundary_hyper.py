"""Spatial semantics, independent enumeration, and legacy isolation checks."""
import copy
import itertools
import pickle
import random
import unittest
from collections import Counter

import numpy as np

from boundary_hyper import BoundaryNetModel, Frontier, TYPES, lift, independent_spans
from physical_model import build, check_cache
from static_regions import RESOURCES


def graph(kinds, nets):
    refs = dict(FF='FDRE', LUT='LUT6', DSP='DSP48E2', BRAM18='RAMB18E2',
                URAM='URAM288', LUTMEM='SRLC32E', CARRY8='CARRY8')
    cells = [dict(primitive=refs[r]) for r in kinds]
    if nets and len(nets[0]) == 2:
        nets = [(f'n{i}', a, tuple(bs), 4) for i, (a, bs) in enumerate(nets)]
    return dict(cells=cells, atoms=[[i] for i in range(len(kinds))],
                atom_of=list(range(len(kinds))), atom_resources=[{r: 1} for r in kinds],
                nets=nets, edges=[(tuple(sorted({a, *bs})), w) for _, a, bs, w in nets
                                 if isinstance(a, int) and all(isinstance(b, int) for b in bs)])


def slot(module, resource):
    return module * len(TYPES) + TYPES.index(resource)


def pattern(*slots):
    return tuple(sorted(Counter(slots).items()))


def device():
    return {f'X{x}Y0':dict(x=x,y=0,slr=x // 2,
            resources={r:(10 if r not in ('DSP','BRAM18','URAM') or
                           x == dict(DSP=2,BRAM18=0,URAM=3).get(r) else 0)
                       for r in RESOURCES}) for x in range(4)}


def region(dev, *xs):
    crs=[f'X{x}Y0' for x in xs]
    return dict(crs=crs,bounds=[min(xs),0,max(xs),0],area=len(xs),
                capacity={r:sum(dev[c]['resources'][r] for c in crs) for r in RESOURCES})


class BoundaryTests(unittest.TestCase):
    def test_internal_ff_lut_ff_is_free_but_cross_is_not(self):
        d=graph(['FF','LUT','FF'],[(0,[1]),(1,[2])])
        self.assertEqual(lift(d,[0,0,0],1)[0],{})
        p,_=lift(d,[0,0,1],2)
        self.assertEqual(p,{pattern(slot(0,'FF'),slot(1,'FF')):1.})

    def test_internal_ram_continuous_ff_chain_stops_at_first_hard(self):
        d=graph(['BRAM18','LUT','FF','FF','DSP','URAM'],
                [(0,[1]),(1,[2]),(2,[3]),(3,[4]),(4,[5])])
        original=copy.deepcopy(d)
        p,_=lift(d,[0]*6,1)
        self.assertEqual(p,{pattern(slot(0,'BRAM18'),slot(0,'DSP')):1.,
                            pattern(slot(0,'DSP'),slot(0,'URAM')):1.})
        self.assertEqual(d,original)

    def test_both_same_and_different_hard_resource_pairs(self):
        for a,b in itertools.product(['DSP','BRAM18','URAM'],repeat=2):
            d=graph([a,'LUT',b],[(0,[1]),(1,[2])])
            self.assertEqual(lift(d,[0]*3,1)[0],{pattern(slot(0,a),slot(0,b)):1.})

    def test_does_not_bridge_ff_across_module_boundary(self):
        d=graph(['BRAM18','FF','DSP'],[(0,[1]),(1,[2])])
        self.assertEqual(lift(d,[0,1,1],2)[0],
                         {pattern(slot(0,'BRAM18'),slot(1,'FF')):1.})
        self.assertEqual(lift(d,[0,0,1],2)[0],
                         {pattern(slot(0,'FF'),slot(1,'DSP')):1.})

    def test_lut_only_transit_module_is_retained(self):
        d=graph(['BRAM18','LUT','DSP'],[(0,[1]),(1,[2])])
        p,_=lift(d,[0,1,2],3)
        self.assertEqual(p,{pattern(slot(0,'BRAM18'),slot(1,'COMB_CENTER'),slot(2,'DSP')):1.})
        p,_=lift(d,[0,1,0],2)
        self.assertEqual(p,{pattern(slot(0,'BRAM18'),slot(1,'COMB_CENTER'),slot(0,'DSP')):1.})

    def test_only_same_hyperedge_anchors_absorb_luts(self):
        d=graph(['BRAM18','LUT','DSP','FF'],[(0,[1]),(1,[2])])
        p,_=lift(d,[0,1,2,1],3)
        self.assertIn(slot(1,'COMB_CENTER'),dict(next(iter(p))))
        p,_=lift(d,[0,0,2,1],3)
        self.assertEqual(p,{pattern(slot(0,'BRAM18'),slot(2,'DSP')):1.})

    def test_reconvergence_and_duplicate_pins_do_not_multiply_paths(self):
        d=graph(['BRAM18','LUT','LUT','LUT','DSP'],
                [('n0',0,(1,2,2),4),('n1',1,(3,),4),('n2',2,(3,),4),('n3',3,(4,4),4)])
        self.assertEqual(lift(d,[0]*5,1)[0],{pattern(slot(0,'BRAM18'),slot(0,'DSP')):1.})
        d['nets'].append(('another_bit',0,(1,2),1))
        self.assertEqual(lift(d,[0]*5,1)[0],{pattern(slot(0,'BRAM18'),slot(0,'DSP')):1.25})

    def test_internal_ff_feedback_terminates(self):
        d=graph(['BRAM18','FF','FF','DSP'],[(0,[1]),(1,[2]),(2,[1,3])])
        p,audit=lift(d,[0]*4,1)
        self.assertEqual(p,{pattern(slot(0,'BRAM18'),slot(0,'DSP')):1.})
        self.assertEqual(audit['internal_frontier']['cyclic_components'],1)

    def test_shared_fanout_is_one_hyperedge(self):
        d=graph(['DSP','LUT','DSP','BRAM18'],[(0,[1]),(1,[2,3])])
        self.assertEqual(lift(d,[0]*4,1)[0],
                         {pattern(slot(0,'DSP'),slot(0,'DSP'),slot(0,'BRAM18')):1.})

    def test_unlocated_ports_do_not_get_fabric_positions(self):
        d=graph(['LUT','FF'],[('port','PORT:in',(0,),4),('out',0,(1,'PORT:out'),4)])
        p,audit=lift(d,[0,1],2)
        self.assertEqual(p,{pattern(slot(0,'COMB_CENTER'),slot(1,'FF')):1.})
        self.assertEqual(audit['unknown_source_nets'],1)
        self.assertEqual(audit['unknown_sink_pins'],1)

    def test_lut_memory_is_not_transparent_comb_logic(self):
        d=graph(['BRAM18','LUTMEM','DSP'],[(0,[1]),(1,[2])])
        self.assertFalse(lift(d,[0]*3,1)[0])

    def test_unrooted_comb_island_keeps_cross_module_cost(self):
        d=graph(['LUT','LUT'],[(0,[1]),(1,[0])])
        p,audit=lift(d,[0,1],2)
        self.assertEqual(p,{pattern(slot(0,'COMB_CENTER'),slot(1,'COMB_CENTER')):2.})
        self.assertEqual(audit['unrooted_comb_fallback_nets'],2)

    def test_frontier_matches_independent_bfs_including_cycles(self):
        rng=random.Random(73)
        for _ in range(60):
            n=8
            adjacency=[{b for b in range(n) if rng.random()<.2} for a in range(n)]
            transparent=[rng.random()<.6 for _ in range(n)]
            labels=[rng.randrange(3) for _ in range(n)]
            for local in [False,True]:
                f=Frontier(adjacency,transparent,labels,same_module=local)
                for root in range(n):
                    visited=set();terminal=set();stack=[root];mask=0
                    while stack:
                        a=stack.pop()
                        if a in visited:continue
                        visited.add(a);mask |= 1 << labels[a]
                        if not transparent[a]:terminal.add(a);continue
                        stack.extend(b for b in adjacency[a] if not local or labels[b]==labels[a])
                    self.assertEqual(f.query([root]),(terminal,mask))

    def test_long_chain_does_not_use_python_recursion(self):
        n=4000
        a=[[i+1] for i in range(n-1)]+[[]]
        f=Frontier(a,[True]*(n-1)+[False],[0]*n)
        self.assertEqual(f.query([0]),({n-1},1))

    def test_budget_failure_is_explicit_not_truncation(self):
        with self.assertRaisesRegex(ValueError,'budget exceeded'):
            Frontier([[1],[2],[]],[True,True,False],[0]*3,max_entries=1)

    def test_costs_match_full_distribution_enumeration(self):
        d=graph(['BRAM18','LUT','FF','DSP'],[(0,[1]),(1,[2,3])])
        dev=device()
        m=BoundaryNetModel(d,[0,1,2,2],3,dev)
        chosen={'P00':region(dev,0,1),'P01':region(dev,0,1,2),'P02':region(dev,1,2,3)}
        c=m.components(chosen,8)
        profiles=[p for i in range(3) for p in m.distributions(chosen[f'P{i:02d}'])]
        exact=np.zeros(3)
        for edge,w in zip(m.patterns,m.weights):
            distributions=[profiles[s] for s,count in edge for _ in range(count)]
            for draw in itertools.product(*distributions):
                mass=float(w)*np.prod([p for _,p in draw])
                for a in range(3):
                    positions=[point[a] for point,_ in draw]
                    exact[a]+=mass*(max(positions)-min(positions))
        self.assertTrue(np.allclose(exact,[c['x_span'],c['y_span'],c['slr_span']]))
        independent=independent_spans(m,chosen)
        self.assertTrue(np.allclose(exact,list(independent.values())))
        self.assertAlmostEqual(c['physical_cost'],exact@[1,1,8])

    def test_mean_proxies_are_not_independent_uniform_luts(self):
        d=graph(['LUT','LUT'],[(0,[1])]);dev=device()
        m=BoundaryNetModel(d,[0,1],2,dev)
        r=region(dev,0,1)
        self.assertAlmostEqual(m.components({'P00':r,'P01':r})['physical_cost'],0.)

    def test_internal_cost_and_pickle_roundtrip(self):
        d=graph(['BRAM18','FF','DSP'],[(0,[1]),(1,[2])]);dev=device()
        m=BoundaryNetModel(d,[0]*3,1,dev);r=region(dev,0,1,2)
        c=m.components({'P00':r},8)
        self.assertAlmostEqual(c['physical_cost'],10.)
        self.assertAlmostEqual(m.internal_region_cost(0,r,8),10.)
        other=pickle.loads(pickle.dumps(m))
        self.assertEqual(other.components({'P00':r},8),c)

    def test_legacy_selection_and_cache_mismatch(self):
        d=graph(['FF','FF'],[(0,[1])]);dev=device()
        old=build(d,[0,0],1,dev,{})
        new=build(d,[0,0],1,dev,dict(hypernet_model='boundary_spatial_v1'))
        r=region(dev,0,1,2)
        self.assertGreater(old.components({'P00':r})['physical_cost'],0.)
        self.assertEqual(new.components({'P00':r})['physical_cost'],0.)
        with self.assertRaisesRegex(ValueError,'rebuild'):
            check_cache(old,dict(hypernet_model='boundary_spatial_v1'))


if __name__=='__main__':unittest.main()
