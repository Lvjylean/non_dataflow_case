"""Transactional physical-edge and bounded-plan admission regressions."""
import copy
import csv
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

import locality_plan as lp


def lut(source, slr='SLR0'):
    return dict(ref='LUT1',slr=slr,x=0,y=0,key='template/O',origin='template',
                config={'INIT':"2'h2"},inputs={'I0':source})


def tsv(path, headers, rows):
    with path.open('w') as f:
        writer=csv.DictWriter(f,fieldnames=headers,delimiter='\t')
        writer.writeheader();writer.writerows(rows)


class GraphTests(unittest.TestCase):
    def test_exact_changes_and_constants(self):
        nets={'root/Q':['a/D','b/D'],'d/Q':['root/D']}
        new=dict(ref='FDRE',inputs={'D':'d/Q','C':'clock sysclk',
                                  'CE':'constant POWER','R':'constant GROUND'})
        g=lp.direct_graph(nets,{'copy':new},{'b/D':'copy/Q'})
        self.assertEqual(g['expected'],{'root/Q':['a/D'],'copy/Q':['b/D'],'d/Q':['copy/D','root/D']})
        self.assertEqual(g['new_inputs']['copy/CE'],'constant POWER')
        self.assertFalse(any(lp.special_source(k) for k in g['expected']))
        self.assertEqual(g['moves'],{'b/D':['root/Q','copy/Q']})

    def test_incremental_matches_one_shot_and_unchanged_nets_absent(self):
        nets={'q/O':['a/I0','b/I0'],'unrelated/O':['c/I0']}
        clones={'one':lut('q/O'),'two':lut('q/O')}
        g=lp.DirectGraph(nets)
        g.admit({'one':clones['one']},{'a/I0':'one/O'})
        g.admit({'two':clones['two']},{'b/I0':'two/O'})
        self.assertEqual(g.graph(),lp.direct_graph(nets,clones,{'a/I0':'one/O','b/I0':'two/O'}))
        self.assertNotIn('unrelated/O',g.graph()['expected'])

    def test_conflicting_candidate_does_not_commit_anything(self):
        g=lp.DirectGraph({'q/O':['s/I0']})
        g.admit({'one':lut('q/O')},{'s/I0':'one/O'})
        before=copy.deepcopy(g.graph())
        with self.assertRaisesRegex(ValueError,'overlapping_sink_owner'):
            g.admit({'two':lut('q/O')},{'s/I0':'two/O'})
        self.assertEqual(g.graph(),before);self.assertNotIn('two',g.clones)

    def test_identical_shared_clone_is_budgeted_once(self):
        g=lp.DirectGraph({'q/O':['a/I0','b/I0']});clone=lut('q/O')
        g.admit({'one':clone},{'a/I0':'one/O'})
        g.admit({'one':clone},{'b/I0':'one/O'})
        self.assertEqual(g.graph()['expected']['q/O'],['one/I0'])
        self.assertEqual(g.graph()['expected']['one/O'],['a/I0','b/I0'])

    def test_shared_upstream_fanout_limit_is_global_and_atomic(self):
        nets={'src/Q':[f's{i}/D' for i in range(98)]}
        g=lp.DirectGraph(nets);g.admit({'one':lut('src/Q')},{})
        self.assertEqual(len(g.graph()['expected']['src/Q']),99)
        before=copy.deepcopy(g.graph())
        with self.assertRaisesRegex(ValueError,'projected_shared_fanout'):
            g.admit({'two':lut('src/Q')},{})
        self.assertEqual(g.graph(),before)

    def test_intra_proposal_dependencies_have_exact_connections(self):
        g=lp.DirectGraph({'q/O':['sink/D']})
        g.admit({'one':lut('q/O'),'two':lut('one/O')},{'sink/D':'two/O'})
        self.assertEqual(g.graph()['expected'],{'q/O':['one/I0'],'one/O':['two/I0'],'two/O':['sink/D']})

    def test_protected_and_clock_sinks_rejected(self):
        cells={'s':dict(editable=False)}
        g=lp.DirectGraph({'q/O':['s/D']},cells)
        with self.assertRaisesRegex(ValueError,'protected_sink'):g.admit({'copy':lut('q/O')},{'s/D':'copy/O'})
        cells['s']['editable']=True
        g=lp.DirectGraph({'q/O':['s/C']},cells)
        with self.assertRaisesRegex(ValueError,'clock_sink'):g.admit({'copy':lut('q/O')},{'s/C':'copy/O'})

    def test_duplicate_or_unknown_driver_and_signal_replacement_fail(self):
        with self.assertRaisesRegex(ValueError,'Multiple drivers'):lp.DirectGraph({'x/O':['s/D'],'y/O':['s/D']})
        g=lp.DirectGraph({'q/O':['s/D']})
        with self.assertRaisesRegex(ValueError,'unknown_source'):g.admit({'copy':lut('missing/O')},{})
        with self.assertRaisesRegex(ValueError,'rewire_changes_signal'):g.admit({}, {'s/D':'constant GROUND'})
        self.assertEqual(g.graph(),dict(expected={},moves={},new_inputs={}))

    def test_boundary_added_load_rejects_protection_async_and_unknown_reasons(self):
        for status in ['asynchronous_register','protected_ip','protected_hierarchy','fixed_route',
                       'clock_driver','clock_used_as_data','ambiguous_driver_count','ambiguous_pin_direction',
                       'unknown_pin_cell','missing_init','unconnected_input','future_unknown_guard']:
            with self.subTest(status=status):
                cells={'src':dict(ref='FDRE',slr='SLR0',x=1,y=1,editable=False,status=status,inputs={})}
                g=lp.DirectGraph({'src/Q':['existing/D']},cells)
                with self.assertRaisesRegex(ValueError,'protected_boundary_source'):
                    g.admit({'new':lut('src/Q')},{})
                self.assertEqual(g.graph(),dict(expected={},moves={},new_inputs={}))

    def test_only_ff_d_port_boundary_is_allowed_for_internal_output(self):
        cell=dict(ref='FDRE',slr='SLR0',x=1,y=1,editable=False,status='port_boundary',inputs={'D':'barrier PORT:data'})
        cells={'src':cell};g=lp.DirectGraph({'src/Q':['existing/D']},cells)
        g.admit({'new':lut('src/Q')},{})
        self.assertEqual(g.graph()['expected']['src/Q'],['existing/D','new/I0'])
        g=lp.DirectGraph({'src/Q':['existing/D','barrier PORT:q']},cells)
        with self.assertRaisesRegex(ValueError,'external_output_boundary'):g.admit({'new':lut('src/Q')},{})
        cell['inputs']={'CE':'barrier PORT:ce'}
        g=lp.DirectGraph({'src/Q':['existing/D']},cells)
        with self.assertRaisesRegex(ValueError,'unsupported_port_boundary_source'):g.admit({'new':lut('src/Q')},{})

    def test_missing_source_metadata_and_unsupported_primitive_fail_closed(self):
        g=lp.DirectGraph({'src/Q':['existing/D']},{})
        with self.assertRaisesRegex(ValueError,'missing_boundary_source'):g.admit({'new':lut('src/Q')},{})
        cells={'src':dict(ref='FDCE',slr='SLR0',x=1,y=1,editable=True,status='',inputs={})}
        g=lp.DirectGraph({'src/Q':['existing/D']},cells)
        with self.assertRaisesRegex(ValueError,'unsupported_boundary_primitive'):g.admit({'new':lut('src/Q')},{})

    def test_supported_memory_output_boundary_can_feed_new_logic(self):
        cells={'ram':dict(ref='URAM288',slr='SLR0',x=1,y=1,editable=True,status='',inputs={})}
        g=lp.DirectGraph({'ram/DOUT_A[0]':['existing/D']},cells)
        g.admit({'new':lut('ram/DOUT_A[0]')},{})
        self.assertEqual(g.graph()['expected']['ram/DOUT_A[0]'],['existing/D','new/I0'])


class PlannerTests(unittest.TestCase):
    def fixture(self,folder):
        cells=[dict(name='ff',ref='FDRE',slr='SLR1',x=3,y=6,init="1'b0",editable='1',status=''),
               dict(name='d',ref='FDRE',slr='SLR0',x=3,y=2,init="1'b0",editable='1',status='')]
        cells += [dict(name=f's{i}',ref='FDRE',slr='SLR0',x=3,y=2,init="1'b0",editable='1',status='') for i in range(16)]
        tsv(folder/'cells.tsv',list(cells[0]),cells)
        edges=[dict(driver='d/Q',sink='ff/D'),dict(driver='constant POWER',sink='ff/CE'),dict(driver='constant GROUND',sink='ff/R')]
        edges += [dict(driver='ff/Q',sink=f's{i}/D') for i in range(16)]
        tsv(folder/'edges.tsv',['driver','sink'],edges)
        tsv(folder/'through_slacks.tsv',['key','max'],[])
        tsv(folder/'template_status.tsv',['cell','status'],[dict(cell='ff',status='supported')])
        tree=dict(clones={},rewires={f's{i}/D':'copy/Q' for i in range(16)},expected={'copy/Q':[f's{i}/D' for i in range(16)]},metadata={'reused_nodes':[]})
        request=dict(id='ff/Q@SLR0',key='ff/Q',replica='copy',target='SLR0',x=3,y=2,terminals=[f's{i}/D' for i in range(16)],tree=tree,effective=16,kind='broadcast')
        (folder/'proposals.json').write_text(json.dumps(dict(requests=[request],cones=[],decisions=[])))
        native,_=lp.inventory(folder)
        inv=types.SimpleNamespace(candidates=[dict(id=request['id'],key='ff/Q',replica='copy',target='SLR0',x='3',y='2',ref='FDRE')],
            used={('SLR0','FF'):0},capacity={('SLR0','FF'):1000,('SLR0','LUT'):1000},cells=native,
            edges={'ff':{'D':dict(key='d/Q',kind='ordinary',source_cell='d'),
                         'C':dict(key='clock sysclk',kind='clock',source_cell=''),
                         'CE':dict(key='constant POWER',kind='constant',source_cell=''),
                         'R':dict(key='constant GROUND',kind='constant',source_cell='')}},
            slacks={'ff/D':{'max':'2','min':'.1'}})
        def build(fake,**kwargs):
            return dict(keep=[request['id']],aux={},links={'copy/D':'d/Q','copy/C':'clock sysclk','copy/CE':'constant POWER','copy/R':'constant GROUND'},
                        owners={request['id']:['ff','d']},estimates={request['id']:dict(mode='ff_only',predicted_D_slack=2.0)})
        return inv,build

    def test_inventory_keeps_constants_as_input_semantics_only(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d);self.fixture(folder);cells,nets=lp.inventory(folder)
            self.assertEqual(cells['ff']['inputs']['CE'],'constant POWER')
            self.assertNotIn('constant POWER',nets)
            self.assertEqual(len(lp.broadcast.discover(cells,nets)['components']),1)

    def test_finish_writes_admitted_graph_with_real_detached_count(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d)/'locality';folder.mkdir();inv,build=self.fixture(folder)
            with patch.object(lp.joint,'Inventory',return_value=inv),patch.object(lp.joint,'build',side_effect=build):lp.finish(folder)
            result=json.loads((folder.parent/'joint_candidates.json').read_text())
            self.assertEqual(result['keep'],['ff/Q@SLR0'])
            self.assertEqual(inv.candidates[0]['detached_loads'],'16')
            self.assertEqual(result['links']['copy/CE'],'constant POWER')
            self.assertIn('bl_reused',(folder/'final_plan.tcl').read_text())

    def test_prepare_exports_local_control_alias_templates(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d);self.fixture(folder)
            cells=lp.read_rows(folder/'cells.tsv');headers=list(cells[0])
            for name,ref,slr in [('ceff','FDRE','SLR1'),('far','LUT1','SLR1'),('local','LUT1','SLR0')]:
                cells.append(dict(name=name,ref=ref,slr=slr,x='3',y='2',init="2'h2" if ref=='LUT1' else "1'b0",editable='1',status=''))
            tsv(folder/'cells.tsv',headers,cells)
            edges=[r for r in lp.read_rows(folder/'edges.tsv') if r['sink']!='ff/CE']
            edges += [dict(driver='ceff/Q',sink='far/I0'),dict(driver='ceff/Q',sink='local/I0'),dict(driver='far/O',sink='ff/CE')]
            tsv(folder/'edges.tsv',['driver','sink'],edges)
            with patch.object(lp.locality,'discover',return_value=dict(candidates=[],rejected=[])):
                lp.prepare(folder)
            request=(folder/'requests.tcl').read_text()
            self.assertIn('set bl_control_aliases',request)
            self.assertRegex(request,r'bl_control_aliases[^\n]*local')
            self.assertNotRegex(request,r'bl_control_aliases[^\n]*far')

    def test_total_and_slr_resource_budgets_reject_before_graph_commit(self):
        for mode,reason in [('total','total_resource_budget'),('slr','slr_resource_budget')]:
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as d:
                folder=Path(d)/'locality';folder.mkdir();inv,build=self.fixture(folder)
                if mode=='slr':inv.capacity[('SLR0','FF')]=0
                with patch.object(lp.joint,'Inventory',return_value=inv),patch.object(lp.joint,'build',side_effect=build):
                    lp.finish(folder,max_added=0 if mode=='total' else 8192)
                result=json.loads((folder.parent/'joint_candidates.json').read_text())
                self.assertEqual(result['keep'],[]);self.assertEqual(result['links'],{})
                self.assertTrue(any(r['status']==reason for r in result['decisions']))

    def test_bounds_are_finite_and_computed_per_slr(self):
        cells={'a':dict(slr='SLR0',x=0,y=1),'b':dict(slr='SLR0',x=7,y=3),'c':dict(slr='SLR1',x=4,y=5)}
        self.assertEqual(lp.slr_bounds(cells),{'SLR0':(0,7,1,3),'SLR1':(4,4,5,5)})
        cells['c']['x']=float('nan')
        self.assertNotIn('SLR1',lp.slr_bounds(cells))

    def test_missing_position_is_none_and_only_affected_candidate_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d)/'locality';folder.mkdir();inv,build=self.fixture(folder)
            rows=lp.read_rows(folder/'cells.tsv');headers=list(rows[0])
            rows.append(dict(name='unrelated',ref='FDRE',slr='SLR3',x='',y='',init="1'b0",editable='1',status=''))
            tsv(folder/'cells.tsv',headers,rows)
            cells,_=lp.inventory(folder);self.assertIsNone(cells['unrelated']['x'])
            with patch.object(lp.joint,'Inventory',return_value=inv),patch.object(lp.joint,'build',side_effect=build):lp.finish(folder)
            self.assertEqual(json.loads((folder.parent/'joint_candidates.json').read_text())['keep'],['ff/Q@SLR0'])
            rows[0]['x']='';tsv(folder/'cells.tsv',headers,rows)
            with patch.object(lp.joint,'Inventory',return_value=inv),patch.object(lp.joint,'build',side_effect=build):lp.finish(folder)
            result=json.loads((folder.parent/'joint_candidates.json').read_text())
            self.assertEqual(result['keep'],[])
            self.assertTrue(any('missing_position:ff' in r['status'] for r in result['decisions']))

    def test_missing_or_failed_template_rejects_without_graph_changes(self):
        for status in [None,'fixed_route']:
            with self.subTest(status=status),tempfile.TemporaryDirectory() as d:
                folder=Path(d)/'locality';folder.mkdir();inv,build=self.fixture(folder)
                tsv(folder/'template_status.tsv',['cell','status'],[] if status is None else [dict(cell='ff',status=status)])
                with patch.object(lp.joint,'Inventory',return_value=inv),patch.object(lp.joint,'build',side_effect=build):lp.finish(folder)
                result=json.loads((folder.parent/'joint_candidates.json').read_text())
                self.assertEqual(result['keep'],[]);self.assertEqual(result['links'],{})
                self.assertTrue(any('unsupported_template:ff:' in r['status'] for r in result['decisions']))

    def test_external_port_barrier_retained_and_never_rewired(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d);self.fixture(folder)
            with (folder/'edges.tsv').open('a') as f:f.write('ff/Q\tbarrier PORT:q[1]\n')
            cells,nets=lp.inventory(folder)
            component=lp.broadcast.discover(cells,nets)['components']['ff/Q']
            self.assertIn('barrier PORT:q[1]',component['barriers'])
            graph=lp.DirectGraph(nets,cells)
            with self.assertRaisesRegex(ValueError,'external_sink'):
                graph.admit({'copy':lut('ff/Q')},{'barrier PORT:q[1]':'copy/O'})


class ContractTests(unittest.TestCase):
    def fixture(self):
        cells={'root':dict(ref='LUT2',slr='SLR0',x=1,y=2,inputs={'I0':'src/Q','I1':'constant POWER'}),
               'src':dict(ref='FDRE',slr='SLR0',x=1,y=2,inputs={})}
        inv=types.SimpleNamespace(cells=copy.deepcopy(cells),edges={'root':{
            'I0':dict(key='src/Q',kind='ordinary',source_cell='src'),
            'I1':dict(key='constant POWER',kind='constant',source_cell='')}})
        return cells,inv

    def test_complete_inputs_constants_and_numeric_positions(self):
        cells,inv=self.fixture();inv.cells['src']['x']='1.0'
        lp.NativeTemplates(cells,inv,{'root':'supported'}).check('root')

    def test_partial_template_and_source_mapping_or_position_rejected(self):
        for mutation,reason in [
            (lambda inv:inv.edges['root'].pop('I1'),'incomplete_template_inputs'),
            (lambda inv:inv.edges['root']['I0'].update(source_cell='wrong'),'template_source_mismatch'),
            (lambda inv:inv.cells['src'].update(x='7'),'native_cell_position_or_ref_mismatch'),
            (lambda inv:inv.edges['root']['I1'].update(key='constant GROUND'),'template_input_mismatch')]:
            with self.subTest(reason=reason):
                cells,inv=self.fixture();mutation(inv)
                with self.assertRaisesRegex(ValueError,reason):lp.NativeTemplates(cells,inv,{'root':'supported'}).check('root')

    def test_cone_requires_supported_same_clock_full_period(self):
        row=dict(max='0.3',status='supported',start_clock='clk',end_clock='clk',period='6.5',requirement='6.500')
        self.assertEqual(lp.cone_timing(row,'x/O'),.3)
        for mutation,reason in [({'status':'exception'},'unsupported_cone_timing'),
                                ({'end_clock':'other'},'unsupported_cone_clock_pair'),
                                ({'requirement':'13'},'unsupported_cone_timing_exception'),
                                ({'period':''},'unsupported_cone_timing_exception'),
                                ({'max':'nan'},'invalid_cone_setup_slack')]:
            with self.subTest(mutation=mutation),self.assertRaisesRegex(ValueError,reason):
                lp.cone_timing(dict(row,**mutation),'x/O')

    def test_ff_native_clock_omission_is_explicit_and_ji_clock_required(self):
        cells={'ff':dict(ref='FDRE',slr='SLR0',x=0,y=0,inputs={'D':'src/Q','CE':'constant POWER','R':'constant GROUND'}),
               'src':dict(ref='FDRE',slr='SLR0',x=0,y=0,inputs={})}
        edges={'D':dict(key='src/Q',kind='ordinary',source_cell='src'),
               'C':dict(key='clock clk',kind='clock',source_cell=''),
               'CE':dict(key='constant POWER',kind='constant',source_cell=''),
               'R':dict(key='constant GROUND',kind='constant',source_cell='')}
        inv=types.SimpleNamespace(cells=copy.deepcopy(cells),edges={'ff':edges})
        lp.NativeTemplates(cells,inv,{'ff':'supported'}).check('ff')
        edges['C']['kind']='ordinary'
        with self.assertRaisesRegex(ValueError,'unsupported_template_clock'):lp.NativeTemplates(cells,inv,{'ff':'supported'}).check('ff')
        del edges['C']
        with self.assertRaisesRegex(ValueError,'incomplete_template_inputs'):lp.NativeTemplates(cells,inv,{'ff':'supported'}).check('ff')


if __name__=='__main__':unittest.main()
