"""Exercise the actual scorer, verifier and rescore CLI without an optimizer."""
import hashlib
import json
from pathlib import Path
import pickle
import shutil
import subprocess
import sys
import tempfile
import unittest

from boundary_hyper import BoundaryNetModel
from boundary_rescore import compare
from balanced_physical import NetModel
from directed_search import Search
from static_regions import RESOURCES, LIMITS, load_device, all_rectangles
from test_boundary_hyper import graph

SOURCE=Path(__file__).resolve().parent


def dump(p,v):p.write_text(json.dumps(v,indent=2)+'\n')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


class IntegrationTests(unittest.TestCase):
    def test_ranking_rejects_legacy_physical_score_under_new_model(self):
        from balanced_deliver import rank
        with tempfile.TemporaryDirectory() as temporary:
            run=Path(temporary);folder=run/'candidates/old';folder.mkdir(parents=True)
            dump(run/'binding.json',dict(all_net_weight=1.))
            dump(folder/'summary.json',{})
            dump(folder/'balanced_regions.json',dict(status='feasible',physical_model='all_atom_v1'))
            with self.assertRaisesRegex(ValueError,'different D_hyper'):
                rank(run,dict(hypernet_model='boundary_spatial_v1'))

    def test_real_search_score_independent_verifier_and_rescore(self):
        with tempfile.TemporaryDirectory() as temporary:
            run=Path(temporary)
            (run/'input/export').mkdir(parents=True)
            (run/'source').mkdir()
            for name in ['fixed11_verify.py','boundary_hyper.py','balanced_physical.py',
                         'static_regions.py','routed_density.py','boundary_directed.py']:
                shutil.copy2(SOURCE/name,run/'source'/name)
            cfg=json.loads((SOURCE/'directed_config.json').read_text())
            cfg.pop('cumulative_paths',None)  # This fixture exercises legacy D_hyper only.
            cfg.pop('directed_distance_model',None)
            cfg['directed_weight']=1.  # Freeze the historical arithmetic fixture.
            cfg['hypernet_weight']=1.
            dump(run/'source/directed_config.json',cfg)
            (run/'input/cr.tsv').write_text('cr\tx\ty\tslr\tSLICEL\tSLICEM\tDSP\tBRAM36\tURAM\n'
                'X0Y0\t0\t0\tSLR0\t10\t10\t0\t10\t0\n'
                'X1Y0\t1\t0\tSLR0\t10\t10\t0\t0\t0\n'
                'X2Y0\t2\t0\tSLR0\t10\t10\t10\t0\t0\n')
            dev=load_device(run/'input/cr.tsv')
            d=graph(['BRAM18','LUT','DSP'],[(0,[1]),(1,[2])])
            model=BoundaryNetModel(d,[0,1,2],3,dev)
            with (run/'netmodel.pkl').open('wb') as stream:pickle.dump(model,stream)
            modules=[dict(module_id=f'S{i:02d}',cells=1,**{r:int(r==kind) for r in RESOURCES})
                     for i,kind in enumerate(['BRAM18','LUT','DSP'])]
            dump(run/'input/export/modules.json',dict(modules=modules,connections=[]))
            wide=next(r for r in all_rectangles(dev) if r['bounds']==[0,0,2,0])
            chosen={m['module_id']:wide for m in modules}
            dump(run/'input/export/static_regions.json',dict(regions=chosen))
            dump(run/'input/original_regions.json',dict(regions=chosen))
            dump(run/'directed.json',dict(module_count=3,families={},
                coverage=dict(modeled_sink_pins=2,same_atom_pins=0),pairs=[
                    dict(source=RESOURCES.index('BRAM18'),sink=len(RESOURCES)+RESOURCES.index('LUT'),weight=1.,pins=1),
                    dict(source=len(RESOURCES)+RESOURCES.index('LUT'),sink=2*len(RESOURCES)+RESOURCES.index('DSP'),weight=1.,pins=1)]))
            dump(run/'binding.json',dict(fixed_partition_cost=7.,hypernet_model='boundary_spatial_v1'))
            search=Search(run)
            self.assertTrue(search.legal(chosen))
            record=search.record('fixed_example',chosen)
            result=dict(record,configuration=cfg,limits=LIMITS,candidate_stats=search.stats,
                        objective=record['components']['J'])
            dump(run/'solution.json',result)
            self.assertAlmostEqual(result['components']['physical_cost'],2.)
            self.assertAlmostEqual(result['components']['directed_distance'],2.)
            self.assertAlmostEqual(result['objective'],11.)
            shutil.copytree(run/'input/export',run/'export')
            dump(run/'local_binding.json',dict(source_sha256={name:sha(run/name) for name in ['netmodel.pkl','directed.json']}))
            dump(run/'source/manifest.json',{p.name:sha(p) for p in (run/'source').iterdir() if p.is_file()})
            checked=subprocess.run([sys.executable,'-B',str(run/'source/fixed11_verify.py'),str(run)],
                                   text=True,capture_output=True)
            self.assertEqual(checked.returncode,0,checked.stdout+checked.stderr)
            self.assertEqual(json.loads((run/'verification.json').read_text())['status'],'PASS')
            # Old and new scores use identical original graph, members and regions.
            with (run/'graph.pkl').open('wb') as stream:pickle.dump(d,stream)
            dump(run/'groups.json',[[0],[1],[2]])
            legacy=NetModel(d,[0,1,2],3,dev).components({f'P{i:02d}':wide for i in range(3)},8)
            old=dict(result,configuration=dict(cfg,hypernet_model='all_atom_v1'),
                     components=dict(result['components'],**legacy))
            old['components']['J']=legacy['physical_cost']+9.
            dump(run/'legacy_solution.json',old)
            comparison=compare(run/'graph.pkl',run/'groups.json',run/'input/cr.tsv',
                               run/'legacy_solution.json',run/'rescore')
            self.assertEqual(comparison['status'],'PASS')
            self.assertAlmostEqual(comparison['J_with_only_D_hyper_changed'],11.)
            with self.assertRaises(FileExistsError):
                compare(run/'graph.pkl',run/'groups.json',run/'input/cr.tsv',
                        run/'legacy_solution.json',run/'rescore')


if __name__=='__main__':unittest.main()
