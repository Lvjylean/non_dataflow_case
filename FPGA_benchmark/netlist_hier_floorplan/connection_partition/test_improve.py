import itertools
import unittest
from collections import Counter

from improve import boundary_refine, labels_for, logical_cores, move_gain, objective, selective_merge
from core_adjust import batch_gain, relocate_cores


def graph(edges, sizes=None, hierarchies=None):
    n = max(max(e) for e,w in edges)+1
    sizes = sizes or [1]*n
    atoms=[]; cells=[]
    for a,size in enumerate(sizes):
        atoms.append(list(range(len(cells),len(cells)+size)))
        for _ in range(size):
            cells.append(dict(original_hierarchy=(hierarchies or ['TOP']*n)[a]))
    return dict(atoms=atoms,cells=cells,active_atoms=list(range(n)),edges=edges,
                atom_resources=[{'FF':s} for s in sizes])


class ImprovementTests(unittest.TestCase):
    def test_batch_gain_matches_simultaneous_multi_source_move(self):
        labels=[0,0,1,2,2]
        for subset_size in range(1,6):
            for subset in itertools.combinations(range(5),subset_size):
                for target in range(3):
                    moving=[v for v in subset if labels[v]!=target]
                    if not moving: continue
                    actual=list(labels)
                    for v in moving: actual[v]=target
                    expected=9*(len(set(labels))-len(set(actual)))
                    self.assertEqual(batch_gain(Counter(labels),Counter(labels[v] for v in moving),target,9),expected)

    def test_whole_core_can_cross_atom_local_minimum_without_splitting_atoms(self):
        data=graph([((0,1),20),((1,2),1000),((2,3),100),((3,4),1000),((4,5),20)])
        groups=[[0,1,2],[3,4,5]]
        unchanged,_=boundary_refine(data,groups,[],strength=0)
        self.assertEqual(unchanged,groups)
        cores=[dict(atoms=[1,2,3,4],hierarchy='core',internal_weight=2100,cells=4)]
        moved,history=relocate_cores(data,groups,cores,strength=.02)
        self.assertTrue(history)
        self.assertLess(objective(data['edges'],labels_for(data,moved))[0],100/4)

    def test_selective_merge_rejects_weak_bridge(self):
        data=graph([((0,1),100),((2,3),100),((1,2),1)])
        groups=[[0,1],[2,3]]
        selective,_=selective_merge(data,groups,.02)
        greedy,_=selective_merge(data,groups,0)
        self.assertEqual(len(selective),2)
        self.assertEqual(len(greedy),1)

    def test_relative_merge_absorbs_attached_fragment_but_respects_cap(self):
        data=graph([((0,1),100),((1,2),10)])
        groups=[[0,1],[2]]
        self.assertEqual(len(selective_merge(data,groups,.5)[0]),1)
        self.assertEqual(len(selective_merge(data,groups,.5,cell_cap=2)[0]),2)

    def test_incremental_gain_matches_enumeration(self):
        for labels in itertools.product(range(3),repeat=4):
            counts=Counter(labels)
            for vertex in range(4):
                for target in range(3):
                    if target==labels[vertex]: continue
                    moved=list(labels);moved[vertex]=target
                    expected=7*(len(set(labels))-len(set(moved)))
                    self.assertEqual(move_gain(counts,labels[vertex],target,7),expected)

    def test_cores_require_internal_cohesion_and_exclude_top(self):
        data=graph([((0,1),20),((1,2),1),((2,3),1),((3,4),20)],
                   hierarchies=['good','good','weak','weak','TOP'])
        cores=logical_cores(data,minimum=2,maximum=4,cohesion=.5)
        self.assertEqual([c['hierarchy'] for c in cores],['good'])

    def test_boundary_moves_preserve_atoms_ownership_and_exact_objective(self):
        data=graph([((0,1),4),((1,2),20),((2,3),12)],sizes=[1,2,1,1])
        groups=[[0,1],[2,3]]
        before=objective(data['edges'],labels_for(data,groups))[0]
        result,detail=boundary_refine(data,groups,[],strength=0,rounds=2,cell_cap=4)
        after=objective(data['edges'],labels_for(data,result))[0]
        self.assertLess(after,before)
        self.assertEqual(sorted(a for g in result for a in g),list(range(4)))
        self.assertTrue(all(sum(len(data['atoms'][a]) for a in g)<=4 for g in result))
        self.assertEqual(detail['history'][-1]['real_km1'],after)


if __name__=='__main__': unittest.main()
