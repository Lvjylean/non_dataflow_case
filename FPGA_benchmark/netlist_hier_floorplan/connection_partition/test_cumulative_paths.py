"""Exhaustive tiny graphs and incremental/full parity without routed feedback."""
import copy
import itertools
import json
from pathlib import Path
import random
import unittest

from cumulative_paths import CumulativePaths, topology, settings, independent_score, penalty
from test_control_paths import graph

CFG=settings(json.loads(Path(__file__).with_name('directed_config.json').read_text()))


def fixture(refs,edges,labels=None):
    d=graph(refs,edges);labels=labels or list(range(len(refs)))
    ids=[f'S{i:02d}' for i in range(max(labels)+1)]
    return topology(d,labels,ids)


def plan(values):return {f'S{i:02d}':dict(slrs=[v]) for i,v in enumerate(values)}


def exhaustive(g,values):
    """Enumerate tiny reference paths, restarting independently at every FF."""
    edges={i:[] for i in range(len(g['owner']))}
    for aa,bb in [g['launch'],*g['layers']]:
        for a,b in zip(aa,bb):edges[int(a)].append(int(b))
    ends={}
    def walk(v,n):
        for b in edges[v]:
            steps=n+abs(values[g['owner'][v]]-values[g['owner'][b]])
            if g['reg'][b]:ends[b]=max(ends.get(b,-1),steps)
            else:walk(b,steps)
    for i,r in enumerate(g['reg']):
        if r:walk(i,0)
    return sum(2**max(0,n-1)-1 for n in ends.values())*128


class CumulativeTests(unittest.TestCase):
    def test_exponential_curve_is_not_a_square(self):
        self.assertEqual([round(128*penalty(n,2)) for n in range(6)],
                         [0,0,128,384,896,1920])

    def test_roundtrip_and_register_reset(self):
        g=fixture(['FDRE','LUT2','FDRE'],[(0,1),(1,2)])
        model=CumulativePaths(g,CFG)
        for values,cost in [([2,1,2],128),([3,1,2],384),([3,2,2],0)]:
            self.assertAlmostEqual(model.components(plan(values))['cumulative_path_term'],cost)
        r=fixture(['FDRE','FDRE','FDRE'],[(0,1),(1,2)])
        self.assertEqual(CumulativePaths(r,CFG).components(plan([2,1,2]))['cumulative_path_term'],0)

    def test_reconvergent_branches_do_not_add_to_one_path(self):
        g=fixture(['FDRE','FDRE','LUT2','FDRE'],[(0,2),(1,2),(2,3)])
        r=CumulativePaths(g,CFG).components(plan([0,0,1,1]),True)
        self.assertEqual(r['cumulative_path_term'],0)
        self.assertEqual(r['cumulative_path_endpoint_histogram'],{1:1})

    def test_all_slr_assignments_match_enumerated_paths(self):
        g=fixture(['FDRE','LUT1','LUT1','FDRE'],[(0,1),(0,2),(1,3),(2,3)])
        model=CumulativePaths(g,dict(CFG,assignment_cache_entries=2))
        for values in itertools.product(range(4),repeat=4):
            result=model.components(plan(values),True)
            self.assertAlmostEqual(result['cumulative_path_term'],exhaustive(g,values))
            reference=independent_score(g,plan(values),CFG)
            for k,v in reference.items():
                if isinstance(v,dict):self.assertEqual(result[k],v)
                else:self.assertAlmostEqual(result[k],v)
        self.assertGreater(model.stats['incremental_propagations'],0)

    def test_random_moves_rejections_and_cache_hits_match_full_recompute(self):
        rng=random.Random(7)
        refs=['FDRE']*2+['LUT2']*15+['FDRE']*3;refs[8]='FDSE'
        edges=[(a,b) for b in range(2,20) for a in rng.sample(range(b),min(3,b))]
        g=fixture(refs,edges,[rng.randrange(5) for _ in refs])
        model=CumulativePaths(g,dict(CFG,assignment_cache_entries=5))
        accepted=[0]*5
        for step in range(150):
            values=list(accepted);values[rng.randrange(5)]=rng.randrange(4)
            actual=model.components(plan(values),True);expected=independent_score(g,plan(values),CFG)
            self.assertEqual(actual['cumulative_path_endpoint_histogram'],expected['cumulative_path_endpoint_histogram'])
            self.assertAlmostEqual(actual['cumulative_path_term'],expected['cumulative_path_term'],places=7)
            if rng.random()<.5:accepted=values
            else:model.components(plan(accepted))

    def test_cached_rejected_state_does_not_corrupt_next_increment(self):
        g=fixture(['FDRE','LUT1','FDRE'],[(0,1),(1,2)])
        m=CumulativePaths(g,CFG)
        for values in [[0,0,0],[2,1,2],[0,0,0],[2,1,1],[2,1,2],[3,0,3]]:
            self.assertAlmostEqual(m.components(plan(values))['cumulative_path_term'],exhaustive(g,values))

    def test_same_slr_xy_move_reuses_assignment_cost(self):
        g=fixture(['FDRE','LUT1','FDRE'],[(0,1),(1,2)])
        m=CumulativePaths(g,CFG);p=plan([2,1,2]);r=m.components(p)
        p['S01']['bounds']=[7,4,7,4]
        self.assertEqual(m.components(p),r);self.assertEqual(m.last_update['visited'],0)

    def test_large_dirty_cone_falls_back_without_truncation(self):
        g=fixture(['FDRE','LUT1','LUT1','FDRE'],[(0,1),(1,2),(2,3)])
        m=CumulativePaths(g,dict(CFG,incremental_max_nodes=1))
        m.components(plan([0,0,0,0]));r=m.components(plan([0,2,1,0]))
        self.assertEqual(m.last_update['mode'],'full_fallback')
        self.assertAlmostEqual(r['cumulative_path_term'],exhaustive(g,[0,2,1,0]))

    def test_opaque_macro_is_reported_not_guessed(self):
        d=graph(['FDRE','DSP48E2','FDRE'],[(0,1),(1,2)])
        with self.assertRaisesRegex(ValueError,'native macro timing'):topology(d,[0,1,2],['S00','S01','S02'])
        g=topology(d,[0,1,2],['S00','S01','S02'],topology_model='ff_cell_v1')
        r=CumulativePaths(g,dict(CFG,topology_model='ff_cell_v1')).components(plan([0,1,2]))
        self.assertEqual(r['cumulative_path_endpoints'],0)
        self.assertEqual(g['coverage']['opaque_source_pins']['DSP48E2'],1)

    def test_unreachable_combinational_island_stays_unreachable(self):
        g=fixture(['LUT1','LUT1','FDRE'],[(0,1),(1,2)])
        m=CumulativePaths(g,CFG)
        for values in [[0,1,2],[2,0,2]]:self.assertEqual(m.components(plan(values))['cumulative_path_endpoints'],0)

    def test_multi_slr_and_missing_owner_fail_closed(self):
        g=fixture(['FDRE','FDRE'],[(0,1)])
        p=plan([0,1]);p['S01']['slrs']=[0,1]
        with self.assertRaisesRegex(ValueError,'single-SLR'):CumulativePaths(g,CFG).components(p)
        d=graph(['FDRE','FDRE'],[(0,1)]);d['atoms']=[[0]]
        with self.assertRaisesRegex(ValueError,'Unowned supported'):topology(d,[0],['S00'])

    def test_overflow_and_invalid_config_are_explicit(self):
        with self.assertRaisesRegex(ValueError,'overflow'):penalty(10000,2)
        for key,value in [('base',1),('base',float('nan')),('weight',0),('incremental_max_nodes',0)]:
            cfg=dict(CFG);cfg[key]=value
            with self.assertRaises(ValueError):settings(dict(cumulative_paths=cfg))
        self.assertIsNone(settings({}))


if __name__=='__main__':unittest.main()
