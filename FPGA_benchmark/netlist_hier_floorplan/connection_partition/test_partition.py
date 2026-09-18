"""Small independent checks for hypernet, resource and ownership semantics."""
import csv
import pickle
import tempfile
import unittest
from pathlib import Path

from partition import linked, normalize_multislr, prepare, rows, summaries, write_table


class ConnectivityTests(unittest.TestCase):
    def test_multislr_merge_preserves_cell_granularity(self):
        data=dict(atoms=[list(range(256)),list(range(256,512))],
                  atom_resources=[{'URAM':256},{'URAM':256}],edges=[((0,1),4)])
        original=dict(groups=[[0],[1]],cell_cap=600)
        merged=normalize_multislr(data,original)
        self.assertEqual(merged['modules'],1)
        self.assertEqual(merged['weighted_km1'],0)
        limited=normalize_multislr(data,dict(original,cell_cap=400))
        self.assertEqual(limited['modules'],2)

    def test_high_fanout_record_is_not_truncated(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'nets.tsv'
            sinks=','.join(f'c{i}:CE' for i in range(25000))
            write_table(path,[dict(net_id='n0',type='SIGNAL',drivers='c25000:Q',sinks=sinks)],
                        ['net_id','type','drivers','sinks'])
            decoded=list(rows(path))
            self.assertEqual(len(decoded[0]['sinks'].split(',')),25000)
            self.assertTrue(decoded[0]['sinks'].endswith('c24999:CE'))

    def test_multi_pin_net_control_weight_ports_and_atoms(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); raw = root/'raw'; raw.mkdir()
            cells = [dict(cell_id=f'c{i}', cell_name=f'cell{i}', primitive=ref,
                          original_hierarchy='TOP') for i,ref in enumerate(
                        ['LUT1','LUT2','FDRE','BUFGCE','GND','MUXF7','LUT1'])]
            write_table(raw/'cells.tsv',cells,['cell_id','cell_name','primitive','original_hierarchy'])
            nets = [('n0','SIGNAL','c0:O','c1:I0,c1:I1'),
                    ('n1','SIGNAL','c1:O','c2:D'),
                    ('n2','SIGNAL','c0:O','c2:CE'),
                    ('n3','SIGNAL','c6:O','c5:I0'),
                    ('n4','SIGNAL','PORT:i','c6:I0'),
                    ('n5','SIGNAL','c2:Q','PORT:o'),
                    ('n6','GROUND','c4:G','c5:I1'),
                    ('n7','CLOCK','c3:O','')]
            with (raw/'nets.tsv').open('w') as f:
                writer=csv.writer(f,delimiter='\t')
                writer.writerow(['net_id','type','drivers','sinks']);writer.writerows(nets)
            (raw/'connectivity_complete.txt').write_text('complete')
            prepare(root)
            with (root/'graph.pkl').open('rb') as f: data=pickle.load(f)
            self.assertEqual(data['atom_of'][5],data['atom_of'][6])
            self.assertEqual(data['totals'],{'LUT':3,'FF':1,'MUXF7':1})
            labels=[0 if 0 in a else 1 for a in data['atoms']]
            result=dict(membership=labels,groups=[[i for i,l in enumerate(labels) if l==m] for m in range(2)],
                        weighted_km1=1.25,weighted_cut=1.25)
            owner, modules, pairs, ports, metrics=summaries(data,result)
            self.assertEqual(pairs['P00','P01']['nets'],2)
            self.assertEqual(pairs['P00','P01']['sink_pin_connections'],3)
            self.assertEqual(metrics['cut_nets'],2)
            self.assertEqual(ports['PORT','P01']['nets'],1)
            self.assertEqual(ports['P01','PORT']['nets'],1)
            self.assertEqual(owner[3:5],['CLOCK','CONSTANT'])
            self.assertEqual(sum(m['cells'] for m in modules),5)

    def test_only_dedicated_cascades_are_atomic(self):
        self.assertTrue(linked('DSP48E2','PCOUT[0]','DSP48E2','PCIN[0]'))
        self.assertFalse(linked('DSP48E2','P[0]','DSP48E2','A[0]'))
        self.assertTrue(linked('CARRY8','CO[7]','CARRY8','CI'))
        self.assertTrue(linked('URAM288','CAS_OUT_DOUT_A[0]','URAM288','CAS_IN_DIN_A[0]'))


if __name__=='__main__': unittest.main()
