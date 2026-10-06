"""Structural coverage, invariant preservation and independent objective checks."""
from collections import Counter
import copy
import itertools
import json
from pathlib import Path
import pickle
import shutil
import tempfile
import unittest
from unittest.mock import patch

from directed_units import build_topology, discover, MoveIndex, refine
from improve import objective, soft_edges
from test_control_paths import graph
from test_macro_timing import fixture as macro_fixture, state
from test_resource_partition import budget

PCFG = dict(cut_weight=1., logical_core_weight=1., core_soft_strength=.1)


def fixture(refs, edges):
    d = graph(refs, edges)
    d['atom_resources'] = [dict(FF=1) if r.startswith('FD') else dict(LUT=1) for r in refs]
    d['edges'] = [(tuple(sorted({a,b})),4) for a,b in edges if a != b]
    return d


def cones(d, protected=(), cfg=None, macro=None):
    return discover(d, build_topology(d, macro), protected, cfg)


class DiscoveryTests(unittest.TestCase):
    def test_data_and_control_branches_use_identical_rules(self):
        d = fixture(['FDRE','LUT2','FDRE','LUT2','MUXF7','FDRE'],
                    [(0,1),(2,3),(1,4),(3,4),(4,5)])
        # Control weight does not exclude a branch from dependency discovery.
        d['nets'][1] = ('anything',2,[3],1)
        rows, audit = cones(d)
        r = next(r for r in rows if r['atoms'] == [1,3,4])
        self.assertEqual(r['anchors'], [0,2,5])
        self.assertEqual(audit['new_hard_units'],0)
        self.assertFalse(audit['uses_names'])

    def test_register_stops_same_cycle_cone(self):
        d = fixture(['FDRE','LUT1','FDRE','LUT1','FDRE'],[(0,1),(1,2),(2,3),(3,4)])
        rows,_ = cones(d)
        self.assertEqual({tuple(r['atoms']) for r in rows},{(1,),(3,)})
        self.assertFalse(any(1 in r['atoms'] and 3 in r['atoms'] for r in rows))

    def test_broadcast_stays_shared_instead_of_merging_consumers(self):
        d = fixture(['FDRE','LUT1','LUT1','LUT1','FDRE','FDRE'],
                    [(0,1),(1,2),(1,3),(2,4),(3,5)])
        rows,_ = cones(d)
        self.assertFalse(any(2 in r['atoms'] and 3 in r['atoms'] for r in rows))
        self.assertFalse(any(1 in r['atoms'] and 2 in r['atoms'] for r in rows))
        self.assertIn([1], [r['atoms'] for r in rows])

    def test_reconvergent_fork_is_admitted_when_all_branches_return(self):
        d = fixture(['FDRE','LUT1','LUT1','LUT1','LUT2','FDRE'],
                    [(0,1),(1,2),(1,3),(2,4),(3,4),(4,5)])
        rows,_ = cones(d)
        self.assertIn([1,2,3,4], [r['atoms'] for r in rows])

    def test_opaque_and_top_port_exits_prevent_false_exclusivity(self):
        for sink in (4,'PORT:out'):
            d = fixture(['FDRE','LUT1','LUT1','FDRE','SRL16E'],[(0,1),(1,2),(2,3)])
            d['nets'].append(('outside',1,[sink],4))
            rows,audit = cones(d)
            self.assertNotIn([1,2],[r['atoms'] for r in rows])
            self.assertGreater(audit['graph_coverage']['escape_guard_cells'],0)
            self.assertEqual(audit['graph_coverage']['unsupported_cells']['SRL16E'],1)

    def test_names_hierarchy_and_net_order_do_not_select_candidates(self):
        d = fixture(['FDRE','LUT1','LUT1','LUT2','FDRE'],[(0,1),(0,2),(1,3),(2,3),(3,4)])
        expected,_ = cones(d)
        renamed = copy.deepcopy(d)
        for i,c in enumerate(renamed['cells']):
            c.update(cell_name=f'other/top/enable{i}',original_hierarchy='arbitrary')
        renamed['nets'] = [(f'control_{i}',a,list(reversed(ss)),w)
                           for i,(_,a,ss,w) in enumerate(reversed(renamed['nets']))]
        self.assertEqual(expected,cones(renamed)[0])

    def test_partial_physical_atom_and_protected_chain_remain_indivisible(self):
        d = fixture(['FDRE','LUT1','FDRE','LUT1','FDRE'],[(0,1),(1,2),(2,3),(3,4)])
        protected = [dict(hierarchy='chain',atoms=[1,3])]
        self.assertEqual(cones(d,protected)[0],[])
        d['atoms'] = [[0],[1,3],[2],[4]]
        d['atom_of'] = [0,1,2,1,3]
        self.assertEqual(cones(d)[0],[])

    def test_bounded_cone_is_not_claimed_complete(self):
        d = fixture(['FDRE','LUT1','LUT1','LUT1','FDRE'],[(0,1),(1,2),(2,3),(3,4)])
        rows,audit = cones(d,cfg=dict(max_cone_nodes=2))
        self.assertEqual(rows,[])
        self.assertEqual(audit['bounded_roots_skipped'],1)

    def test_macro_native_register_and_bypass_semantics(self):
        pins=[(0,'Q',1,'A'),(1,'P',2,'D')]
        _,d,registered = macro_fixture(['FDRE','DSP48E2','FDRE'],pins,state(1,'A','P'))
        self.assertEqual(cones(d,macro=registered)[0],[])
        _,d,bypass = macro_fixture(['FDRE','DSP48E2','FDRE'],pins,[(1,'comb','A','P')])
        self.assertIn([1],[r['atoms'] for r in cones(d,macro=bypass)[0]])
        with self.assertRaisesRegex(ValueError,'native macro timing'):
            cones(d)

    def test_combinational_cycle_fails_closed(self):
        d = fixture(['LUT1','LUT1'],[(0,1),(1,0)])
        with self.assertRaisesRegex(ValueError,'cycle'):
            cones(d)


class MoveTests(unittest.TestCase):
    def setUp(self):
        self.d = fixture(['FDRE','LUT1','LUT1','FDRE'],[(0,1),(1,2),(2,3)])
        self.d['edges'] = [((0,1),4),((1,2),40),((1,3),8),((2,3),8)]
        self.groups = [[0,1,2],[3]]
        self.candidate = dict(id='test',atoms=[1,2],anchors=[0,3])

    def test_joint_move_can_improve_when_each_single_move_cannot(self):
        index = MoveIndex(self.d,self.groups,[],[],budget(),PCFG)
        for a in (1,2):
            self.assertIsNone(index.proposal([a],1,.03)[0])
        p,reason = index.proposal([1,2],1,.03)
        self.assertIsNone(reason)
        self.assertEqual(p['delta_J'],-3)
        before=copy.deepcopy(self.d)
        result,detail=refine(self.d,self.groups,[self.candidate],[],[],budget(),PCFG,.03)
        self.assertEqual(result,[[0],[1,2,3]])
        self.assertEqual(len(detail['moves']),1)
        self.assertEqual(detail['after']['J'],1)
        self.assertEqual(self.d,before)

    def test_exact_resource_affinity_and_protection_gates(self):
        self.d['atom_resources'][3] = dict(LUT=1)
        small = MoveIndex(self.d,self.groups,[],[],budget(cap=2),PCFG)
        self.assertEqual(small.proposal([1,2],1,.03)[1],'resource_budget')
        p=MoveIndex(self.d,self.groups,[],[dict(hierarchy='unit',atoms=[0,1])],budget(),PCFG)
        self.assertEqual(p.proposal([1,2],1,.03)[1],'protected_unit')
        p=MoveIndex(self.d,self.groups,[],[],budget(),PCFG)
        self.assertEqual(p.proposal([1],1,.9)[1],'affinity')

    def test_logical_loss_is_not_dropped_from_joint_objective(self):
        cores=[dict(atoms=[0,1,2],internal_weight=400)]
        index=MoveIndex(self.d,self.groups,cores,[],budget(),PCFG)
        self.assertEqual(index.proposal([1,2],1,.03)[1],'non_improving_J')

    def test_all_multi_atom_deltas_match_independent_full_rescore(self):
        cores=[dict(atoms=[0,2],internal_weight=20),dict(atoms=[1,3],internal_weight=80)]
        for labels in itertools.product(range(2),repeat=4):
            if len(set(labels))<2:continue
            groups=[[a for a,m in enumerate(labels) if m==i] for i in range(2)]
            for mask in itertools.product((False,True),repeat=4):
                aa=[a for a,on in enumerate(mask) if on]
                for target in range(2):
                    index=MoveIndex(self.d,groups,cores,[],budget(99),PCFG)
                    p,_=index.proposal(aa,target,0)
                    new=[target if a in aa else m for a,m in enumerate(labels)]
                    def full(ll):
                        return objective(self.d['edges'],ll)[0]+objective(soft_edges(cores,.1),ll)[0]
                    delta=full(new)-full(labels)
                    self.assertEqual(p is not None,delta < 0)
                    if p:
                        self.assertEqual(p['delta_J'],delta)
                        index.apply(p)
                        self.assertEqual(index.metrics()['J'],full(new))
                        volumes=Counter()
                        for pins,w in self.d['edges']:
                            for m in {new[a] for a in pins}:volumes[m]+=w
                        self.assertEqual(index.volume,volumes)

    def test_zero_move_and_explicit_budget_stop(self):
        _,detail=refine(self.d,self.groups,[self.candidate]*3,[],[],budget(),PCFG,.03,
                        cfg=dict(max_evaluations=1))
        self.assertEqual(detail['evaluations'],1)
        self.assertEqual(detail['stop_reason'],'search_budget')
        self.assertEqual(detail['candidates_completed'],0)
        self.assertFalse(detail['all_candidates_completed'])

    def test_complete_pass_ignores_search_limits_but_caps_actual_moves(self):
        d = fixture(['FDRE','LUT1','LUT1','FDRE']*2, [])
        d['edges'] = self.d['edges'] + [(tuple(a+4 for a in pins),w) for pins,w in self.d['edges']]
        candidates = [self.candidate,dict(id='second',atoms=[5,6],anchors=[4,7]),
                      dict(self.candidate,id='overlap')]
        progress = []
        with patch('directed_units.time.monotonic',side_effect=itertools.count()):
            result, detail = refine(d,[[0,1,2],[3],[4,5,6],[7]],candidates,[],[],budget(),PCFG,.03,
                seconds=.001,max_moves=1,cfg=dict(max_evaluations=1),complete_pass=True,
                progress=progress.append)
        self.assertEqual(result,[[0],[1,2,3],[4,5,6],[7]])
        self.assertEqual(len(detail['moves']),1)
        self.assertEqual(len(detail['deferred_improvements']),1)
        self.assertEqual(detail['deferred_improvements'][0]['candidate'],'second')
        self.assertTrue(detail['acceptance_limit_reached'])
        self.assertEqual(detail['candidates_completed'],3)
        self.assertEqual(detail['evaluations'],6)
        self.assertEqual(detail['stop_reason'],'all_candidates_visited')
        self.assertEqual(detail['ordered_candidate_ids_sha256'],detail['completed_candidate_ids_sha256'])
        self.assertEqual(detail['effective_limits'],dict(seconds=None,max_evaluations=12,max_moves=1))
        self.assertTrue(detail['all_candidates_completed'])
        self.assertEqual(progress[-1]['candidates_completed'],3)
        self.assertEqual(detail['after']['J'],5)
        self.assertEqual(sum(detail['rejections'].values())+detail['improving_proposals'],detail['evaluations'])

    def test_complete_pass_optional_uncapped_moves(self):
        result,detail=refine(self.d,self.groups,[self.candidate],[],[],budget(),PCFG,.03,
                             complete_pass=True,max_moves=None)
        self.assertEqual(result,[[0],[1,2,3]])
        self.assertEqual(len(detail['moves']),1)
        self.assertFalse(detail['acceptance_limit_reached'])

    def test_empty_complete_pass_is_certified_without_moves(self):
        result,detail=refine(self.d,self.groups,[],[],[],budget(),PCFG,.03,complete_pass=True)
        self.assertEqual(result,self.groups)
        self.assertTrue(detail['all_candidates_completed'])
        self.assertEqual(detail['evaluations'],0)
        self.assertEqual(detail['before'],detail['after'])


class EntryPointTests(unittest.TestCase):
    def test_frozen_cache_trial_and_parameter_inheritance(self):
        from directed_unit_pipeline import validate, prepare
        from improve import digest
        from structure_pipeline import setup
        source=Path(__file__).resolve().parent
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);run=root/'reference'
            (run/'source').mkdir(parents=True)
            (run/'balanced/candidates/selected').mkdir(parents=True)
            (run/'balanced/candidates/baseline5').mkdir()
            (run/'balanced/baseline/final').mkdir(parents=True)
            def dump(p,v):p.write_text(json.dumps(v))
            for name in ['balanced_config.json','directed_config.json','resource_partition_config.json',
                         'structure_config.json','static_regions.py']:
                shutil.copy2(source/name,run/'source'/name)
            pcfg=json.loads((run/'source/balanced_config.json').read_text())
            pcfg.update(PCFG)
            dump(run/'source/balanced_config.json',pcfg)
            rcfg=json.loads((run/'source/resource_partition_config.json').read_text())
            rcfg.update(merge_affinity_threshold=.03,joint_chains=dict(enabled=False))
            rcfg['resource_ratios']={r:1. if r=='URAM' else .6 for r in rcfg['resource_ratios']}
            dump(run/'source/resource_partition_config.json',rcfg)
            d=fixture(['FDRE','LUT1','LUT1','FDRE'],[(0,1),(1,2),(1,3),(2,3)])
            weights=[4,40,8,8]
            d['edges']=[(aa,w) for (aa,_),w in zip(d['edges'],weights)]
            d['nets']=[(n,a,ss,w) for (n,a,ss,_),w in zip(d['nets'],weights)]
            d.update(totals=dict(FF=2,LUT=2),stats={},active_atoms=list(range(4)))
            for c in d['cells']:c['original_hierarchy']='TOP'
            with (run/'graph.pkl').open('wb') as stream:pickle.dump(d,stream)
            dump(run/'balanced/binding.json',dict(graph_sha256=digest(run/'graph.pkl')))
            dump(run/'balanced/baseline/final/modules.json',dict(input_sha256='fixture-dcp'))
            dump(run/'balanced/cores.json',[])
            dump(run/'balanced/selection.json',dict(selected='selected'))
            dump(run/'balanced/candidates/selected/groups.json',[[0,1,2],[3]])
            dump(run/'balanced/candidates/baseline5/groups.json',[[0],[1],[2],[3]])
            (run/'cr.tsv').write_text('slr\tSLICEL\tSLICEM\tDSP\tBRAM36\tURAM\n0\t4\t0\t0\t0\t0\n')
            original=digest(run/'graph.pkl')
            with patch('physical_model.build',side_effect=AssertionError('position used')):
                result=validate(run,None,root/'trial')
            self.assertTrue(result['candidate_eligible'])
            self.assertEqual(result['after']['J'],1)
            self.assertEqual(result['parameters']['merge_affinity_threshold'],.03)
            self.assertFalse(result['floorplan_run'])
            self.assertEqual(digest(run/'graph.pkl'),original)
            from directed_cached_refine import read_candidates
            cache=root/'trial/discovery'
            cached,_=read_candidates(run,cache,d)
            self.assertEqual(len(cached),result['candidates'])
            payload=(cache/'candidates.pkl').read_bytes()
            (cache/'candidates.pkl').write_bytes(payload+b'corrupt')
            with self.assertRaisesRegex(ValueError,'payload hash mismatch'):
                read_candidates(run,cache,d)
            (cache/'candidates.pkl').write_bytes(payload)
            cache_binding=json.loads((cache/'binding.json').read_text())
            dump(cache/'binding.json',dict(cache_binding,protection_manifest_sha256='wrong'))
            with self.assertRaisesRegex(ValueError,'protection binding mismatch'):
                read_candidates(run,cache,d)
            dump(cache/'binding.json',cache_binding)
            setup(root/'fresh',run,preserve_partition_settings=True)
            for name in ['balanced_config.json','resource_partition_config.json','structure_config.json']:
                self.assertEqual(digest(run/'source'/name),digest(root/'fresh/source'/name))
            self.assertTrue((root/'fresh/balanced/baseline/final/modules.json').exists())
            dump(run/'balanced/binding.json',dict(graph_sha256='wrong'))
            with self.assertRaisesRegex(ValueError,'binding mismatch'):
                prepare(run,d,[],None,root/'must_not_prepare')
            self.assertFalse((root/'must_not_prepare').exists())


if __name__=='__main__':unittest.main()
