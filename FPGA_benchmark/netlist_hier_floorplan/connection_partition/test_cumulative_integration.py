"""Real search/scorer/verifier and graph-bound cache migration on tiny inputs."""
import copy
import csv
import gzip
import json
from pathlib import Path
import pickle
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from boundary_hyper import BoundaryNetModel
from directed_search import Search
from improve import digest
import path_cache
from static_regions import RESOURCES, LIMITS, load_device, all_rectangles
from test_boundary_hyper import graph
import floorplan_cached

SOURCE=Path(__file__).resolve().parent
def dump(path,value):path.write_text(json.dumps(value,indent=2)+'\n')


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name);self.run=self.root/'run';r=self.run
        (r/'input/export').mkdir(parents=True)
        shutil.copytree(SOURCE,r/'source',ignore=shutil.ignore_patterns('__pycache__'))
        self.cfg=json.loads((SOURCE/'directed_config.json').read_text());self.cfg['local_rounds']=1
        self.cfg.pop('directed_distance_model',None)  # Separate legacy spatial fixture.
        self.cfg['directed_weight']=1.  # Preserve the fixture's explicit arithmetic.
        self.cfg['hypernet_weight']=1.
        dump(r/'source/directed_config.json',self.cfg)
        (r/'input/cr.tsv').write_text('cr\tx\ty\tslr\tSLICEL\tSLICEM\tDSP\tBRAM36\tURAM\n'+
            ''.join(f'X0Y{i}\t0\t{i}\tSLR{i}\t10\t10\t10\t10\t10\n' for i in range(4)))
        self.dev=load_device(r/'input/cr.tsv');self.d=graph(['FF','LUT','FF'],[(0,[1]),(1,[2])])
        for i,c in enumerate(self.d['cells']):c.update(cell_id=f'c{i}',cell_name=f'top/c{i}',original_hierarchy='top')
        with (self.root/'graph.pkl').open('wb') as f:pickle.dump(self.d,f)
        self.ids=['S00','S01','S02']
        self.modules=[dict(module_id=m,cells=1,**{res:int(res==kind) for res in RESOURCES})
            for m,kind in zip(self.ids,['FF','LUT','FF'])]
        dump(r/'input/export/modules.json',dict(modules=self.modules,connections=[]))
        with gzip.open(r/'input/export/leaf_cells.tsv.gz','wt') as f:
            writer=csv.DictWriter(f,fieldnames=['cell_id','cell_name','primitive','original_hierarchy','module_id'],delimiter='\t')
            writer.writeheader()
            for c,m in zip(self.d['cells'],self.ids):writer.writerow(dict(c,module_id=m))
        self.regions={r['slrs'][0]:r for r in all_rectangles(self.dev) if r['area']==1}
        self.chosen={m:self.regions[s] for m,s in zip(self.ids,[2,1,2])}
        dump(r/'input/export/static_regions.json',dict(regions=self.chosen))
        dump(r/'input/original_regions.json',dict(regions=self.chosen))
        with (r/'netmodel.pkl').open('wb') as f:pickle.dump(BoundaryNetModel(self.d,[0,1,2],3,self.dev),f)
        dump(r/'directed.json',dict(module_count=3,families={},
             coverage=dict(modeled_sink_pins=2,same_atom_pins=0),pairs=[
                dict(source=1,sink=9,weight=1,pins=1),dict(source=9,sink=19,weight=1,pins=1)]))
        dump(r/'binding.json',dict(fixed_partition_cost=7.,hypernet_model='boundary_spatial_v1',
            input_dcp='/fixture/post_opt.dcp',input_sha256='a'*64,graph_sha256=digest(self.root/'graph.pkl')))
        path_cache.write(r,self.d,[0,1,2],self.ids,digest(self.root/'graph.pkl'))
        self.bind()

    def bind(self):
        dump(self.run/'local_binding.json',dict(source_sha256={str(p.relative_to(self.run)):digest(p)
            for p in [self.run/'netmodel.pkl',self.run/'directed.json',*[self.run/n for n in path_cache.FILES]]}))
        dump(self.run/'source/manifest.json',{p.name:digest(p) for p in (self.run/'source').iterdir()
             if p.is_file() and p.name!='manifest.json'})

    def export_and_verify(self,search,chosen):
        r=self.run;record=search.record('path_fixture',chosen)
        result=dict(record,configuration=self.cfg,limits=LIMITS,candidate_stats=search.stats,
                    objective=record['components']['J'])
        dump(r/'solution.json',result);shutil.copytree(r/'input/export',r/'export')
        self.bind()
        checked=subprocess.run([sys.executable,'-B',str(r/'source/fixed11_verify.py'),str(r)],
                               text=True,capture_output=True)
        self.assertEqual(checked.returncode,0,checked.stdout+checked.stderr)
        result=json.loads((r/'verification.json').read_text())
        self.assertTrue(result['cumulative_paths_verified'])

    def test_real_score_and_final_verifier_include_exponential_term(self):
        search=Search(self.run);r=search.score(self.chosen,True)
        self.assertAlmostEqual(r['cumulative_path_term'],128.)
        self.assertAlmostEqual(r['J'],r['old_J']+r['directed_term']+r['branch_square_term']+128.)
        self.export_and_verify(search,self.chosen)

    def test_real_coordinate_search_uses_new_cost_on_all_candidates(self):
        search=Search(self.run);before=search.score(self.chosen)['J']
        chosen,_=search.refine(self.chosen,0)
        self.assertLess(search.score(chosen)['J'],before)
        self.assertEqual(search.score(chosen)['cumulative_path_term'],0)
        self.assertTrue(all(len(r['slrs'])==1 for values in search.options.values() for r in values))
        self.export_and_verify(search,chosen)

    def test_hypernet_reweight_preserves_raw_cost_and_other_terms(self):
        self.enable_boundary_distance()
        before=Search(self.run).score(self.chosen,True)
        self.cfg['hypernet_weight']=.1
        dump(self.run/'source/directed_config.json',self.cfg)
        search=Search(self.run);after=search.score(self.chosen,True)
        for key in ['physical_cost','directed_term','branch_square_term','cumulative_path_term','fixed_partition_cost']:
            self.assertEqual(after[key],before[key])
        self.assertAlmostEqual(after['hypernet_term'],.1*before['physical_cost'])
        self.assertAlmostEqual(after['J'],before['J']-.9*before['physical_cost'])
        self.export_and_verify(search,self.chosen)

    def test_missing_hypernet_weight_replays_historical_unit_weight(self):
        before=Search(self.run).score(self.chosen,True)
        self.cfg.pop('hypernet_weight')
        dump(self.run/'source/directed_config.json',self.cfg)
        search=Search(self.run);after=search.score(self.chosen,True)
        self.assertEqual(after['J'],before['J'])
        self.assertEqual(after['hypernet_term'],after['physical_cost'])
        self.export_and_verify(search,self.chosen)

    def test_parallel_search_preserves_inputs_and_passes_independent_verifier(self):
        from parallel_floorplan import solve
        self.enable_boundary_distance()
        self.cfg['hypernet_weight']=.1;self.cfg['directed_weight']=.1
        dump(self.run/'source/directed_config.json',self.cfg)
        old=self.root/'old_candidates.json'
        dump(old,[dict(tag='old',regions=self.chosen)])
        membership=digest(self.run/'input/export/leaf_cells.tsv.gz')
        initial=Search(self.run).score(self.chosen)['J']
        result=solve(self.run,old,workers=2,steps=16,seeds=[211,228])
        self.assertLessEqual(result['objective'],initial+1e-6)
        self.assertEqual(result['parallel_workers'],2)
        self.assertEqual(membership,digest(self.run/'export/leaf_cells.tsv.gz'))
        self.assertEqual([p['status'] for p in json.loads((self.run/'parallel_status.json').read_text())['completed']],['PASS','PASS'])
        self.bind()
        checked=subprocess.run([sys.executable,'-B',str(self.run/'source/fixed11_verify.py'),str(self.run)],text=True,capture_output=True)
        self.assertEqual(checked.returncode,0,checked.stdout+checked.stderr)

    def test_legacy_setting_can_be_replayed_without_new_cache(self):
        self.cfg.pop('cumulative_paths');dump(self.run/'source/directed_config.json',self.cfg)
        (self.run/'path_topology.pkl').unlink()
        r=Search(self.run).score(self.chosen)
        self.assertNotIn('cumulative_path_term',r)

    def test_enabled_missing_cache_cannot_silently_use_old_cost(self):
        (self.run/'path_topology.pkl').unlink()
        with self.assertRaises(FileNotFoundError):Search(self.run)

    def test_membership_tampering_is_rejected_before_scoring(self):
        with gzip.open(self.run/'input/export/leaf_cells.tsv.gz','at') as f:f.write('bad\n')
        with self.assertRaisesRegex(ValueError,'membership changed'):Search(self.run)

    def test_multi_slr_trial_rejected_without_zeroing_path_cost(self):
        search=Search(self.run)
        p=dict(self.chosen);p['S01']=next(r for r in all_rectangles(self.dev) if len(r['slrs'])==2)
        self.assertFalse(search.legal(p))
        with self.assertRaisesRegex(ValueError,'single-SLR'):search.score(p)

    def test_cache_reuse_preserves_bound_topology(self):
        self.enable_boundary_distance()
        out=self.root/'cached'
        floorplan_cached.prepare(out,self.run,[])
        self.assertEqual(digest(out/'path_topology.pkl'),digest(self.run/'path_topology.pkl'))
        self.assertAlmostEqual(Search(out).score(self.chosen)['cumulative_path_term'],128)
        self.assertIn('path_topology.pkl',json.loads((out/'local_binding.json').read_text())['source_sha256'])

    def test_ff_only_path_cache_is_rebuilt_for_macro_model(self):
        self.enable_boundary_distance()
        for n in path_cache.FILES:(self.run/n).unlink()
        path_cache.write(self.run,self.d,[0,1,2],self.ids,digest(self.root/'graph.pkl'),topology_model='ff_cell_v1')
        self.bind()
        with self.assertRaisesRegex(ValueError,'Stale'):Search(self.run)
        out=self.root/'migrated'
        floorplan_cached.prepare(out,self.run,[],self.root/'graph.pkl')
        self.assertEqual(path_cache.read(out)['topology_model'],'macro_timing_v2')
        self.assertAlmostEqual(Search(out).score(self.chosen)['cumulative_path_term'],128.)

    def test_historical_ff_only_configuration_still_replays(self):
        for n in path_cache.FILES:(self.run/n).unlink()
        path_cache.write(self.run,self.d,[0,1,2],self.ids,digest(self.root/'graph.pkl'),topology_model='ff_cell_v1')
        self.cfg['cumulative_paths'].pop('topology_model')
        dump(self.run/'source/directed_config.json',self.cfg)
        self.assertAlmostEqual(Search(self.run).score(self.chosen)['cumulative_path_term'],128.)

    def test_old_pair_cache_can_build_from_original_graph(self):
        for n in path_cache.FILES:(self.run/n).unlink()
        out=self.root/'rebuilt';floorplan_cached.prepare(out,self.run,[],self.root/'graph.pkl')
        self.assertAlmostEqual(Search(out).score(self.chosen)['cumulative_path_term'],128)

    def enable_boundary_distance(self):
        from boundary_hyper import lift
        self.cfg['directed_distance_model']='boundary_directed_v1'
        dump(self.run/'source/directed_config.json',self.cfg)
        raw=json.loads((self.run/'directed.json').read_text())
        raw['spatial']=lift(self.d,[0,1,2],3,with_directed=True)[2]
        raw['spatial']['binding']=dict(module_ids=self.ids,graph_sha256=digest(self.root/'graph.pkl'),
            membership_sha256=digest(self.run/'input/export/leaf_cells.tsv.gz'))
        dump(self.run/'directed.json',raw);self.bind()

    def test_new_directed_distance_reaches_score_and_independent_verifier(self):
        old=Search(self.run).score(self.chosen,True)
        self.enable_boundary_distance()
        search=Search(self.run);new=search.score(self.chosen,True)
        # Source star retains the independent transit module's mean position.
        self.assertAlmostEqual(new['directed_distance'],9.)
        self.assertAlmostEqual(old['directed_distance'],18.)
        self.assertEqual(new['cumulative_path_term'],old['cumulative_path_term'])
        self.assertEqual(new['branch_square_term'],old['branch_square_term'])
        self.export_and_verify(search,self.chosen)

    def test_new_config_rejects_unlifted_directed_cache(self):
        self.cfg['directed_distance_model']='boundary_directed_v1'
        dump(self.run/'source/directed_config.json',self.cfg)
        with self.assertRaisesRegex(ValueError,'rebuild'):Search(self.run)

    def test_boundary_mip_uses_new_roles_when_gurobi_available(self):
        try:import gurobipy
        except ImportError:self.skipTest('Gurobi unavailable')
        self.enable_boundary_distance();search=Search(self.run);search.cfg['mip_seconds']=2
        chosen,status=search.mip(0,self.chosen)
        self.assertIsNotNone(chosen)
        self.assertTrue(search.legal(chosen))
        self.assertIn('cumulative_path_term',search.score(chosen))

    def test_fixed_layout_rescore_keeps_paths_and_regions(self):
        from boundary_directed_rescore import compare
        search=Search(self.run)
        record=search.record('rescore_fixture',self.chosen)
        dump(self.run/'solution.json',dict(record,configuration=self.cfg))
        result=compare(self.run,self.root/'graph.pkl',self.root/'rescore')
        self.assertAlmostEqual(result['after']['J'],result['before']['J']-9.)
        self.assertEqual(result['after']['cumulative_path_term'],result['before']['cumulative_path_term'])
        self.assertEqual(json.loads((self.run/'solution.json').read_text())['regions'],self.chosen)

    def test_new_spatial_cache_rejects_changed_membership_without_paths(self):
        self.enable_boundary_distance();self.cfg.pop('cumulative_paths')
        dump(self.run/'source/directed_config.json',self.cfg)
        with gzip.open(self.run/'input/export/leaf_cells.tsv.gz','at') as f:f.write('bad\n')
        with self.assertRaisesRegex(ValueError,'membership changed'):Search(self.run)

    def test_old_pair_cache_without_graph_fails_before_output_creation(self):
        for n in path_cache.FILES:(self.run/n).unlink()
        (self.root/'graph.pkl').unlink();out=self.root/'missing'
        with self.assertRaisesRegex(ValueError,'supply --graph'):floorplan_cached.prepare(out,self.run,[])
        self.assertFalse(out.exists())

    def test_changed_source_graph_hash_is_rejected(self):
        for n in path_cache.FILES:(self.run/n).unlink()
        (self.root/'graph.pkl').write_bytes(b'wrong')
        with self.assertRaisesRegex(ValueError,'graph-bound'):path_cache.preflight(self.run,self.cfg)

    def test_pipeline_setup_carries_current_path_policy_into_frozen_configs(self):
        from structure_pipeline import setup
        old=self.root/'previous';(old/'planning_source').mkdir(parents=True)
        for name in ['balanced_config.json','directed_config.json','static_regions.py']:
            shutil.copy2(SOURCE/name,old/'planning_source'/name)
        previous_cfg=copy.deepcopy(self.cfg);previous_cfg.pop('cumulative_paths')
        dump(old/'planning_source/directed_config.json',previous_cfg)
        shutil.copy2(self.root/'graph.pkl',old/'graph.pkl');shutil.copy2(self.run/'input/cr.tsv',old/'cr.tsv')
        (old/'balanced/candidates/baseline5').mkdir(parents=True);(old/'baseline').mkdir()
        dump(old/'balanced/cores.json',[]);dump(old/'balanced/candidates/baseline5/groups.json',[[0],[1],[2]])
        dump(old/'balanced/binding.json',dict(graph_sha256=digest(old/'graph.pkl')))
        out=self.root/'new_pipeline';setup(out,old)
        cfg=json.loads((out/'source/directed_config.json').read_text())
        self.assertEqual(cfg['cumulative_paths'],self.cfg['cumulative_paths'])
        self.assertEqual(cfg['resource_limits'],previous_cfg['resource_limits'])
        self.assertEqual(cfg['directed_distance_model'],'boundary_directed_v1')
        self.assertEqual(cfg['directed_weight'],json.loads((SOURCE/'directed_config.json').read_text())['directed_weight'])
        self.assertEqual(cfg['hypernet_weight'],json.loads((SOURCE/'directed_config.json').read_text())['hypernet_weight'])


if __name__=='__main__':unittest.main()
