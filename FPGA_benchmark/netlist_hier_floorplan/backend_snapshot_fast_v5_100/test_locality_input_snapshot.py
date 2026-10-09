"""Targeted extraction completeness, exact Tcl escaping and bounded fallback."""
import csv
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

MODULES = Path(__file__).parent/'code'/'regional'
sys.path.insert(0, str(MODULES))
import locality_input_snapshot as snapshot


def write_table(path, fields, rows):
    with path.open('w') as stream:
        writer = csv.DictWriter(stream, fields, delimiter='\t', lineterminator='\n')
        writer.writeheader(); writer.writerows(rows)


class TargetedInputSnapshotTests(unittest.TestCase):
    def fixture(self, folder):
        cells = {
            'src': dict(ref='FDRE', inputs={'D':'constant GROUND','CE':'constant POWER','R':'constant GROUND'}),
            'a': dict(ref='LUT1', inputs={'I0':'src/Q'}),
            'b': dict(ref='LUT1', inputs={'I0':'src/Q'}),
            'mux': dict(ref='MUXF7', inputs={'I0':'a/O','I1':'b/O','S':'src/Q'}),
            'root': dict(ref='FDRE', inputs={'D':'mux/O','CE':'src/Q','R':'constant GROUND'}),
        }
        nets = {'src/Q':['a/I0','b/I0','mux/S','root/CE','opaque/A[0]'],
                'a/O':['mux/I0'], 'b/O':['mux/I1'], 'mux/O':['root/D'], 'root/Q':[]}
        metadata = [('status','PASS'), ('reuse_schema',snapshot.SCHEMA), ('reuse_epoch','7')]
        write_table(folder/'metadata.tsv', ['key','value'], [dict(key=k,value=v) for k,v in metadata])
        rows = [dict(key=k,root='native_'+k,type='SIGNAL',sinks=len(v),safe=1) for k,v in nets.items()]
        write_table(folder/'reuse_nets.tsv', ['key','root','type','sinks','safe'], rows)
        return cells, nets, [dict(key='root/Q')], rows

    def evaluate(self, folder, command):
        script = 'source '+str(folder/'input_snapshot.tcl')+'\n'+command+'\n'
        return subprocess.check_output(['tclsh'], input=script.encode()).decode().strip()

    def test_all_mux_inputs_native_sinks_and_empty_outputs_are_retained(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);cells,nets,requests,_=self.fixture(folder)
            before=repr((cells,nets))
            stats=snapshot.emit_prepared(folder,cells,nets,requests,{'root','mux'})
            self.assertEqual(repr((cells,nets)), before)
            self.assertEqual(stats['retained_cells'], 5)
            self.assertEqual(self.evaluate(folder,'puts [lsort [dict keys [dict get $locality_reuse_snapshot cells mux]]]'), 'I0 I1 S')
            self.assertEqual(self.evaluate(folder,'puts [lsearch -exact [dict get $locality_reuse_snapshot nets src/Q before] {opaque/A[0]}]'), '3')
            self.assertEqual(self.evaluate(folder,'puts [llength [dict get $locality_reuse_snapshot nets root/Q before]]'), '0')

    def test_count_mismatch_fixed_port_and_nonunique_metadata_fall_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);cells,nets,requests,rows=self.fixture(folder)
            rows[0]['sinks'] += 1; rows[1]['safe']=0; rows.append(rows[2].copy())
            write_table(folder/'reuse_nets.tsv', ['key','root','type','sinks','safe'], rows)
            stats=snapshot.emit_prepared(folder,cells,nets,requests,{'root','mux'})
            self.assertEqual(stats['unsafe_net_fallback'], 2)
            self.assertEqual(stats['ambiguous_net_fallback'], 1)
            self.assertEqual(self.evaluate(folder,'puts [lsort [dict keys [dict get $locality_reuse_snapshot nets]]]'), 'mux/O root/Q')

    def test_missing_mux_select_and_ff_control_never_become_smaller_cones(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);cells,nets,requests,_=self.fixture(folder)
            del cells['mux']['inputs']['S']
            del cells['root']['inputs']['CE']
            snapshot.emit_prepared(folder,cells,nets,requests,{'root','mux'})
            self.assertEqual(self.evaluate(folder,'puts [dict exists $locality_reuse_snapshot cells mux]'), '0')
            self.assertEqual(self.evaluate(folder,'puts [dict exists $locality_reuse_snapshot cells root]'), '0')

    def test_ff_clock_is_always_native_even_if_a_clock_descriptor_is_supplied(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);cells,nets,requests,_=self.fixture(folder)
            root='clk [4] $bad {x} \\ path'
            cells['root']['inputs']['C']='clock '+root
            cells['src']['inputs']['C']='constant GROUND'
            snapshot.emit_prepared(folder,cells,nets,requests,{'root','mux'})
            self.assertEqual(self.evaluate(folder,'puts [dict exists $locality_reuse_snapshot cells root C]'), '0')
            self.assertEqual(self.evaluate(folder,'puts [dict exists $locality_reuse_snapshot cells src C]'), '0')
            self.assertEqual(self.evaluate(folder,'puts [dict get $locality_reuse_snapshot cells root CE value]'), 'src/Q')

    def test_missing_capture_epoch_or_sidecars_yields_empty_native_view(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);cells,nets,requests,_=self.fixture(folder)
            (folder/'reuse_nets.tsv').unlink()
            stats=snapshot.emit_prepared(folder,cells,nets,requests,{'root','mux'})
            self.assertEqual(stats['snapshot_unavailable'], 1)
            self.assertEqual(self.evaluate(folder,'puts [dict size [dict get $locality_reuse_snapshot cells]]'), '0')
            write_table(folder/'metadata.tsv',['key','value'],[dict(key='status',value='PASS')])
            stats=snapshot.emit_prepared(folder,cells,nets,requests,{'root','mux'})
            self.assertEqual(stats['reason'], 'missing_current_capture_epoch')

    def test_cell_load_and_byte_budgets_are_native_fallbacks(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);cells,nets,requests,_=self.fixture(folder)
            with patch.object(snapshot,'MAX_CELLS',2), patch.object(snapshot,'MAX_LOADS',0):
                stats=snapshot.emit_prepared(folder,cells,nets,requests,{'root','mux'})
            self.assertEqual(stats['cell_budget_fallback'],1)
            self.assertLessEqual(stats['selected_cells'],2)
            self.assertEqual(stats['retained_loads'],0)
            with patch.object(snapshot,'MAX_BYTES',1300):
                stats=snapshot.emit_prepared(folder,cells,nets,requests,{'root','mux'})
            self.assertEqual(stats['byte_budget_fallback'],1)
            self.assertGreater(stats['serialized_cell_records'], 0)
            self.assertGreater(stats['serialized_net_records'], 0)
            self.assertLessEqual(stats['serialized_bytes'], 1300)
            self.assertEqual(self.evaluate(folder,'puts [dict get $locality_reuse_snapshot cells a I0 value]'),'src/Q')


if __name__ == '__main__':
    unittest.main()
