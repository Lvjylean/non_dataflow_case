"""Check safe boundaries and independence from names/coordinates."""
import unittest
from mux_cone_refine import apply, discover, receiver_targets


def fixture():
    refs = ['URAM288', 'RAMB36E2', 'LUT6', 'MUXF7', 'LUT6', 'FDRE']
    return dict(cells=[dict(primitive=r, original_hierarchy='arbitrary') for r in refs],
        atoms=[[0], [1], [2, 3], [4], [5]], atom_of=[0, 1, 2, 2, 3, 4],
        atom_resources=[{'URAM':1}, {'BRAM18':2}, {'LUT':1,'MUXF7':1}, {'LUT':1}, {'FF':1}],
        nets=[('a',0,[2],4), ('b',1,[2],4), ('inner',2,[3],4), ('out',3,[4],4)])


class MuxRefineTest(unittest.TestCase):
    def test_complete_atom_and_shared_upstream_remains(self):
        data=fixture(); labels=[0,1,0,1,0]
        data['nets'][0][2].append(5)
        proposals,_=discover(data,labels,{0})
        self.assertEqual([(p['atom'],p['target']) for p in proposals],[(2,1)])
        self.assertEqual(apply(labels,proposals),[0,1,1,1,0])

    def test_shared_output_rejects_ambiguous_assignment(self):
        data=fixture();data['nets'][-1][2].append(5)
        self.assertEqual(discover(data,[0,1,0,1,0],{0})[0],[])

    def test_protected_operator_is_not_split_or_moved(self):
        data=fixture(); labels=[0,1,0,1,0]
        units=[dict(hierarchy='complete_operator',atoms=[2,4])]
        self.assertEqual(discover(data,labels,{0},units)[0],[])
        with self.assertRaises(ValueError):
            apply(labels,[dict(atom=2,source=0,target=1)],units)

    def test_memory_control_only_is_not_data_evidence(self):
        data=fixture();data['nets'][0]=('a',0,[2],1)
        self.assertEqual(discover(data,[0,1,0,1,0],{0})[0],[])

    def test_receiver_traversal_stops_at_first_ff(self):
        data=fixture();labels=[0,1,0,1,2]
        data['nets'] += [('capture',4,[5],4),('next_cycle',5,[0],4)]
        p,_=discover(data,labels,{0})
        self.assertEqual(receiver_targets(data,labels,p)[0]['target'],2)
        self.assertEqual(receiver_targets(data,labels,p,max_nodes=1)[0]['target'],1)


if __name__=='__main__':unittest.main()
