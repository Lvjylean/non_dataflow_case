import copy
from pathlib import Path
import subprocess
import tempfile
import unittest

from edge_padding import expand, region_from_crs, regions_tcl, geometry_adapter
from static_regions import RESOURCES


class EdgePaddingTests(unittest.TestCase):
    def setUp(self):
        self.device={f'X{x}Y{y}':dict(x=x,y=y,slr=y//2,resources=dict.fromkeys(RESOURCES,100))
                     for x in range(5) for y in range(4)}

    def plan(self, entries):
        modules=[dict(module_id=mid,**dict(dict.fromkeys(RESOURCES,0),LUT=demand)) for mid,crs,demand in entries]
        regions={mid:region_from_crs(crs,self.device) for mid,crs,_ in entries}
        return modules,dict(regions=regions)

    def test_strict_threshold_and_single_ring_no_diagonals(self):
        modules,plan=self.plan([('A',['X2Y1'],50)])
        self.assertEqual(expand(modules,plan,self.device)[1]['claims'],[])
        modules[0]['LUT']=51
        chosen,record=expand(modules,plan,self.device)
        self.assertEqual(set(chosen['A']['crs']),{'X2Y1','X1Y1','X3Y1','X2Y0'})
        self.assertEqual(chosen['A']['shape'],'CR_union')
        self.assertNotIn('X2Y2',chosen['A']['crs'])  # Other SLR.
        self.assertNotIn('X0Y1',chosen['A']['crs'])  # No second ring.
        self.assertNotIn('X1Y0',chosen['A']['crs'])  # No diagonal fill.

    def test_aggregate_pressure_all_eligible_modules_share_order_independently(self):
        modules,plan=self.plan([('A',['X2Y1'],30),('B',['X2Y1'],30)])
        chosen,record=expand(modules,plan,self.device)
        self.assertEqual(record['changed_modules'],['A','B'])
        self.assertEqual(chosen['A'],chosen['B'])
        self.assertEqual((record['added_unique_crs'],record['added_module_crs'],record['shared_new_crs']),(3,6,3))
        self.assertTrue(all(c['modules']==['A','B'] for c in record['claims']))
        self.assertTrue(all(e['peak']==.6 for c in record['claims'] for e in c['evidence']))
        self.assertEqual(expand(list(reversed(modules)),plan,self.device)[0],chosen)
        reversed_plan=dict(plan,regions=dict(reversed(list(plan['regions'].items()))))
        self.assertEqual(expand(modules,reversed_plan,self.device),(chosen,record))

    def test_occupied_cr_is_never_added(self):
        modules,plan=self.plan([('A',['X2Y1'],60),('B',['X1Y1'],1)])
        chosen,record=expand(modules,plan,self.device)
        self.assertNotIn('X1Y1',chosen['A']['crs'])
        self.assertEqual(chosen['B'],plan['regions']['B'])

    def test_both_edges_share_even_when_utilization_differs(self):
        modules,plan=self.plan([('A',['X0Y0'],60),('B',['X2Y0'],70)])
        chosen,record=expand(modules,plan,self.device)
        self.assertIn('X1Y0',chosen['B']['crs'])
        self.assertIn('X1Y0',chosen['A']['crs'])
        self.assertEqual(next(c['modules'] for c in record['claims'] if c['cr']=='X1Y0'),['A','B'])

    def test_multiple_edges_of_one_module_do_not_duplicate_addition(self):
        modules,plan=self.plan([('A',['X1Y0','X0Y1'],120)])
        chosen,record=expand(modules,plan,self.device)
        target=next(c for c in record['claims'] if c['cr']=='X0Y0')
        self.assertEqual(target['modules'],['A'])
        self.assertEqual(len(target['evidence']),2)
        self.assertEqual(chosen['A']['crs'].count('X0Y0'),1)
        self.assertEqual(record['added_module_crs'],record['added_unique_crs'])

    def test_shared_projection_does_not_remove_eligible_soft_regions(self):
        from static_regions import overlap_audit, LIMITS
        device={c:copy.deepcopy(self.device[c]) for c in ['X0Y0','X1Y0','X2Y0']}
        device['X1Y0']['resources']['LUT']=1
        modules,plan=self.plan([('A',['X0Y0'],60),('B',['X2Y0'],60)])
        self.assertTrue(overlap_audit(modules,plan['regions'],device,LIMITS)['valid'])
        chosen,record=expand(modules,plan,device)
        self.assertEqual(set(chosen['A']['crs']),{'X0Y0','X1Y0'})
        self.assertEqual(set(chosen['B']['crs']),{'X2Y0','X1Y0'})
        self.assertFalse(overlap_audit(modules,chosen,device,LIMITS)['valid'])

    def test_export_expands_geometry_but_preserves_core_resources_and_cost(self):
        import json
        import shutil
        from unittest.mock import patch
        from edge_padding_export import generate
        from static_regions import LIMITS, overlap_audit
        device={c:copy.deepcopy(self.device[c]) for c in ['X0Y0','X1Y0','X2Y0']}
        device['X1Y0']['resources']['LUT']=1
        modules,plan=self.plan([('S00',['X0Y0'],60),('S01',['X2Y0'],60)])
        plan.update(status='feasible',overlap=overlap_audit(modules,plan['regions'],device,LIMITS),
                    total_module_crs=2,families={},objective=123,tag='selected',
                    limits=LIMITS,configuration=dict(slr_distance_weight=4),components=dict(fixed_partition_cost=123))
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);previous=root/'reference';run=root/'output'
            (previous/'export').mkdir(parents=True);(previous/'input').mkdir();(run/'source').mkdir(parents=True)
            (previous/'implementation_input/export').mkdir(parents=True)
            raw=json.dumps(plan)
            for p in ['solution.json','export/static_regions.json','implementation_input/export/static_regions.json']:
                (previous/p).write_text(raw)
            meta=dict(modules=modules,input_dcp='/unused-test-fixture.dcp',input_sha256='unused',validation=dict(all_cells=2))
            (previous/'export/modules.json').write_text(json.dumps(meta))
            for p in ['input/cr.tsv','netmodel.pkl','implementation_input/membership.tsv']:(previous/p).write_text('fixture')
            (previous/'directed.json').write_text('{}')
            (previous/'implementation_input/manifest.json').write_text('{}')
            adapter=Path(__file__).resolve().parent.parent/'balanced_implementation/adapter.tcl'
            shutil.copy2(adapter,run/'source/adapter_reference.tcl')
            # The cache is deliberately invalid: a geometry-only export must not
            # load it or re-evaluate costs from the expanded envelope.
            with patch('edge_padding_export.load_device',return_value=device):
                generate(run,previous)
            output=json.loads((run/'solution.json').read_text())
            self.assertEqual(output['status'],'soft_envelope_ready')
            self.assertTrue(output['uniform_overlap_pass'])
            self.assertEqual(output['overlap'],plan['overlap'])
            self.assertEqual(output['planning_regions'],plan['regions'])
            self.assertEqual(output['components'],plan['components'])
            self.assertEqual(output['objective'],plan['objective'])
            self.assertEqual(output['total_module_crs'],2)
            self.assertEqual(output['soft_geometry']['total_module_crs'],4)
            self.assertIsNone(output['soft_diagnostic_objective'])
            self.assertTrue(all('capacity' not in r for r in output['regions'].values()))
            self.assertNotIn('X1Y0',{c['cr'] for c in output['overlap']['contributions']})
            for mid in ['S00','S01']:self.assertIn('X1Y0',output['regions'][mid]['crs'])
            self.assertEqual((run/'core_solution.json').read_text(),raw)
            self.assertEqual(output['core_objective'],123)
            self.assertIn('soft_region_adapter.tcl',json.loads((run/'implementation_input/manifest.json').read_text())['files'])

    def test_full_slr_has_no_expansion_and_repeat_is_rejected(self):
        modules,plan=self.plan([('A',[c for c,d in self.device.items() if d['slr']==0],600)])
        self.assertEqual(expand(modules,plan,self.device)[1]['claims'],[])
        plan['edge_padding']={}
        with self.assertRaises(ValueError):expand(modules,plan,self.device)

    def test_export_uses_only_the_J_selected_unexpanded_core(self):
        from edge_padding_export import validate_core
        core=dict(status='feasible',overlap=dict(valid=True),objective=123)
        validate_core(core)
        for key in ['soft_padding','soft_override','edge_padding']:
            with self.assertRaises(ValueError):validate_core(dict(core,**{key:{}}))
        with self.assertRaises(ValueError):validate_core(dict(core,status='soft_envelope_ready'))

    def test_expansion_does_not_mutate_selected_core_or_objective(self):
        modules,plan=self.plan([('A',['X2Y1'],60)])
        plan.update(objective=123,tag='J_selected')
        snapshot=copy.deepcopy(plan)
        chosen,_=expand(modules,plan,self.device)
        self.assertNotEqual(chosen,plan['regions'])
        self.assertEqual(plan,snapshot)

    def test_other_resource_triggers_without_requiring_it_in_neighbor(self):
        modules,plan=self.plan([('A',['X2Y1'],0)])
        modules[0]['URAM']=100
        self.device['X1Y1']['resources']['URAM']=0
        self.assertIn('X1Y1',expand(modules,plan,self.device)[0]['A']['crs'])

    def test_exact_cr_adapter_does_not_fill_nonrectangular_holes(self):
        modules,plan=self.plan([('A',['X2Y1'],60)])
        chosen,_=expand(modules,plan,self.device)
        adapter=Path(__file__).resolve().parent.parent/'balanced_implementation/adapter.tcl'
        with tempfile.TemporaryDirectory() as temp:
            tcl=Path(temp)/'regions.tcl';tcl.write_text(regions_tcl(chosen))
            (Path(temp)/'soft_region_adapter.tcl').write_text(geometry_adapter(adapter))
            script='source {'+str(adapter)+'}\nsource {'+str(tcl)+'}\n'
            script+='puts [join [bi_ranges A] \\n]\n'
            result=subprocess.run(['tclsh'],input=script,text=True,capture_output=True,check=True)
            self.assertFalse(result.stderr,result.stderr)
            expected={f'CLOCKREGION_{c}:CLOCKREGION_{c}' for c in chosen['A']['crs']}
            self.assertEqual(set(result.stdout.splitlines()),expected)
            standalone=subprocess.run(['tclsh'],input='source {'+str(tcl)+'}\nputs [llength [bi_ranges A]]\n',text=True,capture_output=True)
            self.assertFalse(standalone.stderr,standalone.stderr)
            self.assertEqual(standalone.stdout.strip(),'4')

    def test_cache_distinguishes_equal_bounds_with_different_cr_sets(self):
        from balanced_physical import NetModel
        from directed_model import DirectedModel
        import numpy as np
        a=region_from_crs(['X0Y0','X1Y0','X1Y1'],self.device)
        b=region_from_crs(['X0Y0','X0Y1','X1Y1'],self.device)
        self.assertEqual(a['bounds'],b['bounds'])
        net=object.__new__(NetModel);net.device=self.device;net._cache={}
        self.assertFalse(np.array_equal(net.cdf(a),net.cdf(b)))
        dm=DirectedModel(dict(module_count=1,pairs=[]),self.device,{})
        self.assertFalse(np.array_equal(dm.profile(a)[0],dm.profile(b)[0]))


if __name__=='__main__':unittest.main()
