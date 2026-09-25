"""Invariants for reversible contraction and original-graph group refinement."""
import copy
import itertools
import unittest

from structure_frontend import contract, cut_metrics, discover, expand, label_groups
from structure_refine import OriginalIndex, components, refine


def fixture():
    names = ['source', 'top/dsub_example_U/reg', 'top/dsub_example_U/core', 'side']
    cells = [dict(cell_id=f'c{i}', cell_name=n, primitive='FDRE',
                  original_hierarchy=n.rsplit('/',1)[0] if '/' in n else 'TOP') for i,n in enumerate(names)]
    return dict(cells=cells, atoms=[[i] for i in range(4)], atom_of=list(range(4)),
                atom_resources=[dict(FF=1) for _ in cells],
                edges=[((0,1),4),((1,2),4)],
                nets=[('in',0,(1,),4),('out',1,(2,2,2),4)],active_atoms=list(range(4)))


CFG = dict(operator_min_cells=1,operator_max_cells=100,
           operator_min_cohesion=.5,operator_min_connected_fraction=.9,
           local_search_seconds=10,local_max_moves=10,loose_module_connected_fraction=.9)


class StructureTests(unittest.TestCase):
    def test_all_coarse_assignments_preserve_cut_and_km1(self):
        data=fixture()
        data['edges'] += [((0,1,2),8),((0,2),3),((1,2),2),((2,3),1)]
        data['atom_resources'][1]=dict(LUT=3,LUTMEM=2,DSP=1)
        data['atom_resources'][2]=dict(BRAM18=2,URAM=1)
        units=[dict(atoms=[1,2])]
        original=copy.deepcopy(data)
        coarse,mapping,info=contract(data,units)
        for labels in itertools.product(range(3),repeat=len(mapping)):
            fine=[None]*4
            for q,aa in enumerate(mapping):
                for a in aa:fine[a]=labels[q]
            self.assertEqual(cut_metrics(coarse['edges'],labels),cut_metrics(data['edges'],fine))
        self.assertEqual(coarse['atom_resources'][0],dict(LUT=3,LUTMEM=2,DSP=1,BRAM18=2,URAM=1))
        self.assertEqual(data,original)
        self.assertIsNot(coarse,data)
        self.assertNotIn('nets',coarse)
        self.assertTrue(info['original_graph_required_for_scoring'])

    def test_isolated_coarse_vertex_and_all_members_survive(self):
        data=fixture();data['edges']=[((1,2),4)]
        coarse,mapping,_=contract(data,[dict(atoms=[1,2])])
        self.assertEqual(coarse['edges'],[])
        groups=expand([list(range(len(mapping)))],mapping,4)
        self.assertEqual(sorted(groups[0]),list(range(4)))
        self.assertEqual(sum(map(len,coarse['atoms'])),4)

    def test_connections_validate_name_proposals(self):
        data=fixture();units,audit=discover(data,CFG)
        self.assertEqual(len(units),1)
        self.assertEqual(units[0]['atoms'],[1,2])
        data['nets']=[('in',0,(1,2),4)]
        units,audit=discover(data,CFG)
        self.assertFalse(units)
        self.assertIn('internally_fragmented',audit[0]['rejection_reasons'])

    def test_physical_atom_cannot_be_split_by_operator_boundary(self):
        data=fixture();data['atoms']=[[0],[1,3],[2]];data['atom_of']=[0,1,2,1]
        data['atom_resources']=[dict(FF=1),dict(FF=2),dict(FF=1)]
        units,audit=discover(data,CFG)
        self.assertFalse(units)
        self.assertIn('crosses_physical_atom',audit[0]['rejection_reasons'])

    def test_duplicate_members_and_overlapping_operators_fail(self):
        with self.assertRaises(ValueError):label_groups([[0,1],[1,2]],3)
        with self.assertRaises(ValueError):contract(fixture(),[dict(atoms=[1,2]),dict(atoms=[2,3])])

    def test_batch_deltas_match_independent_full_recount(self):
        data=fixture();data['edges'] += [((0,1,2,3),5),((0,2),1)]
        data['nets'] += [('mixed',2,(0,1,1,3,'PORT:q'),1)]
        for initial in itertools.product(range(2),repeat=4):
            if set(initial)!={0,1}:continue
            groups=[[a for a,m in enumerate(initial) if m==q] for q in range(2)]
            index=OriginalIndex(data,groups,[])
            before=index.total()
            for atoms in [[0],[1,2],[0,1,3]]:
                for target in range(2):
                    proposal=index.proposal(atoms,target)
                    if proposal is None:continue
                    after=list(initial)
                    for a in atoms:after[a]=target
                    km=cut_metrics(data['edges'],after)['weighted_km1']
                    branches=sum(w/4 for _,d,ss,w in data['nets'] for s in ss
                                 if isinstance(s,int) and after[d]!=after[s])
                    self.assertEqual(km-before['weighted_km1'],proposal['delta_km1'])
                    self.assertEqual(branches-before['weighted_cross_pins'],proposal['delta_weighted_cross_pins'])

    def test_input_register_repair_can_keep_km1_reduce_fanout_cost(self):
        data=fixture();units,_=discover(data,CFG)
        index=OriginalIndex(data,[[0,1],[2,3]],units)
        proposal=index.proposal([1],1)
        self.assertEqual(proposal['delta_km1'],0)
        self.assertEqual(proposal['delta_weighted_cross_pins'],-2)
        result,detail=refine(data,[[0,1],[2,3]],units,CFG)
        labels=label_groups(result,4)
        self.assertEqual(labels[1],labels[2])
        self.assertLessEqual(detail['after']['weighted_km1'],1)
        self.assertLessEqual(detail['after']['weighted_cross_pins'],1)
        self.assertEqual(detail['after']['split_operators'],0)
        self.assertTrue(detail['history'])

    def test_external_broadcast_does_not_connect_internal_sinks(self):
        data=fixture();data['nets']=[('broadcast',0,(1,2,3),4)]
        result=components(data,[0,1,1,1])
        self.assertEqual(len(result[1]),3)

    def test_complete_operator_protected_during_local_round(self):
        data=fixture();index=OriginalIndex(data,[[0,1,2],[3]],[dict(atoms=[1,2])])
        self.assertIsNone(index.proposal([1],1))

    def test_zero_budget_leaves_membership_unchanged(self):
        data=fixture();units,_=discover(data,CFG)
        groups=[[0,1],[2,3]]
        result,detail=refine(data,groups,units,dict(CFG,local_search_seconds=0))
        self.assertEqual(result,groups)
        self.assertTrue(detail['time_budget_reached'])

    def test_operator_only_stage_keeps_component_merges_optional(self):
        data=fixture();units,_=discover(data,CFG)
        groups=[[0,1],[2,3]]
        result,detail=refine(data,groups,units,dict(CFG,move_components=False))
        self.assertEqual(len(result),2)
        self.assertEqual(detail['after']['split_operators'],0)
        self.assertLessEqual(detail['after']['weighted_km1'],1)
        self.assertLessEqual(detail['after']['weighted_cross_pins'],1)
        self.assertTrue(all(x['kind']=='operator_repair' for x in detail['history']))
        groups=[[0],[1,2,3]]
        only,_=refine(data,groups,units,dict(CFG,move_components=False))
        full,detail=refine(data,groups,units,CFG)
        self.assertEqual(only,groups)
        self.assertNotEqual(full,groups)
        self.assertLess(detail['after']['weighted_km1'],detail['before']['weighted_km1'])


if __name__=='__main__':unittest.main()
