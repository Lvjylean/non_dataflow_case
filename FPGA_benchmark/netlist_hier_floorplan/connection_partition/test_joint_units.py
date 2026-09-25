import unittest
from joint_units import batch_move, protection_units, validate_units
from structure_frontend import contract, cut_metrics, label_groups


def graph():
    return dict(atoms=[[0],[1],[2],[3]], atom_of=[0,1,2,3],
                atom_resources=[{'DSP':1} for _ in range(4)],
                nets=[('a',0,[1],4),('b',1,[2],4),('c',2,[3],4)],
                edges=[([0,1],4),([1,2],4),([2,3],4)])


class JointUnitsTest(unittest.TestCase):
    def test_connected_compound_and_exact_quotient_cut(self):
        d=graph(); ops=[dict(hierarchy='a',atoms=[0,1])]
        units=validate_units(d,[dict(hierarchy='chain',atoms=[0,1,2],stages=[[0,1],[2]])],ops,lambda q:q['DSP']<=3)
        coarse,mapping,_=contract(d,protection_units(ops,units))
        self.assertEqual(cut_metrics(coarse['edges'],[0,1]),cut_metrics(d['edges'],[0,0,0,1]))

    def test_batch_swap_uses_final_capacity(self):
        d=graph();g=[[0,1],[2,3]]; units=[dict(hierarchy='a',atoms=[1]),dict(hierarchy='b',atoms=[2])]
        out=batch_move(d,g,units,{'a':1,'b':0},lambda q:q['DSP']<=2)
        self.assertEqual(out,[[0,2],[1,3]])
        self.assertEqual(g,[[0,1],[2,3]])
        with self.assertRaises(ValueError):batch_move(d,g,units,{'a':1},lambda q:q['DSP']<=2)

    def test_disconnected_and_partial_operator_rejected(self):
        d=graph()
        with self.assertRaises(ValueError):
            validate_units(d,[dict(hierarchy='x',atoms=[0,3],stages=[[0],[3]])],[],lambda q:True)
        with self.assertRaises(ValueError):
            validate_units(d,[dict(hierarchy='x',atoms=[0,1],stages=[[0],[1]])],[dict(atoms=[1,2])],lambda q:True)

    def test_protected_and_resource_failures(self):
        d=graph()
        with self.assertRaises(ValueError):
            validate_units(d,[dict(hierarchy='x',atoms=[0,1],stages=[[0],[1]])],[],lambda q:q['DSP']<=1)
        with self.assertRaises(ValueError):
            batch_move(d,[[0,1],[2,3]],[dict(hierarchy='a',atoms=[1])],{'a':1},lambda q:True,protected=[dict(atoms=[0,1])])

    def test_invalid_or_overlapping_groups_fail_closed(self):
        with self.assertRaisesRegex(ValueError,'multiple coallocation'):
            protection_units([dict(atoms=[0,1])],[dict(atoms=[0]),dict(atoms=[1])])
        with self.assertRaises(ValueError):
            protection_units([], [dict(atoms=[0,1]),dict(atoms=[1,2])])
        with self.assertRaises(ValueError):
            batch_move(graph(),[[0,1],[2,3]],[dict(hierarchy='a',atoms=[-1])],{'a':1},lambda q:True)
        with self.assertRaises(ValueError):
            batch_move(graph(),[[0,1],[2,3]],[],{'missing':1},lambda q:True)


if __name__=='__main__':unittest.main()
