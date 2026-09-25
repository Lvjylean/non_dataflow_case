"""Resource-only partition invariants and cache-to-export integration."""
from collections import Counter
import copy
import csv
import itertools
import json
from pathlib import Path
import pickle
import shutil
import tempfile
import unittest
from unittest.mock import patch

import partition as base
from resource_partition import (Budget, profile_from_cr_table, recursive_groups, selective_merge,
                                score, rank_rows, projected_core_edges)
from structure_frontend import cut_metrics, label_groups
from structure_refine import OriginalIndex
from test_structure_frontend import fixture

SOURCE=Path(__file__).resolve().parent
RATIOS={r:1. if r=='URAM' else .7 for r in base.RESOURCES}
CFG=dict(partition_objective='resource_logic_v1',cut_weight=2.,logical_core_weight=2.,core_soft_strength=.1)


def budget(cap=10,average=2):
    return Budget(dict(resource_ratios={r:1. for r in base.RESOURCES},
        die_capacity_classes=[{r:cap for r in base.RESOURCES}],
        average_usable_cr={r:average for r in base.RESOURCES}))


def exhaustive_split(root,data,vertices,k,caps,weights,tag,seed):
    candidates=[]
    for rest in itertools.product((0,1),repeat=len(vertices)-1):
        labels=(0,)+rest
        if len(set(labels))<2:continue
        groups=[[a for a,m in zip(vertices,labels) if m==j] for j in range(2)]
        if any(sum(weights[a] for a in g)>caps[i] for i,g in enumerate(groups)):continue
        owner=dict(zip(vertices,labels))
        cost=sum(w*(len({owner[a] for a in pins if a in owner})>1) for pins,w in data['edges'])
        candidates.append((cost,groups))
    return min(candidates)[1]


class ResourceTests(unittest.TestCase):
    def test_common_die_vector_not_componentwise_best(self):
        profile=copy.deepcopy(budget().profile)
        profile['die_capacity_classes'][0].update(DSP=10,BRAM18=2)
        profile['die_capacity_classes'].append(dict(profile['die_capacity_classes'][0],DSP=2,BRAM18=10))
        b=Budget(profile)
        self.assertFalse(b.fits(dict(DSP=8,BRAM18=8)))
        self.assertTrue(b.fits(dict(DSP=8,BRAM18=2)))
        self.assertFalse(b.fits(dict(LUTMEM=11)))

    def test_dominant_resource_equivalent_size_not_equal_mix(self):
        b=budget()
        self.assertEqual(b.equivalent_crs(dict(DSP=2)),1)
        self.assertEqual(b.equivalent_crs(dict(DSP=2,LUT=2)),1)
        self.assertTrue(b.fits(dict(DSP=10)))
        self.assertTrue(b.fits(dict(LUT=1)))
        b.average['URAM']=0
        self.assertEqual(b.equivalent_crs(dict(URAM=1)),float('inf'))

    def test_capacity_table_ignores_coordinates_and_die_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            a=Path(tmp)/'a.tsv';b=Path(tmp)/'b.tsv'
            header='slr\tSLICEL\tSLICEM\tDSP\tBRAM36\tURAM\tx\ty\n'
            a.write_text(header+'SLR0\t2\t1\t10\t5\t4\t0\t0\nSLR1\t1\t2\t8\t3\t6\t1\t4\n')
            b.write_text(header+'arbitraryB\t1\t2\t8\t3\t6\t999\t-8\narbitraryA\t2\t1\t10\t5\t4\t-4\t32\n')
            first=profile_from_cr_table(a,RATIOS)
            self.assertEqual(first,profile_from_cr_table(b,RATIOS))
            self.assertAlmostEqual(first['average_usable_cr']['LUT'],16.8)
            self.assertEqual(first['average_usable_cr']['URAM'],5)
            caps=Budget(first).caps
            self.assertEqual(max(c['DSP'] for c in caps),7)

    def test_no_D_or_count_in_score_and_no_near_score_tie(self):
        from balanced_physical import balanced_score
        metric=dict(weighted_km1=10,logical_core_loss=2,module_count=99)
        self.assertEqual(balanced_score(None,metric,1e30,CFG),24)
        self.assertEqual(balanced_score(dict(x_span=1e99),dict(metric,module_count=1),0,CFG),24)
        rows=[dict(metric,candidate='many',resource_feasible=True),
              dict(metric,candidate='few',module_count=2,weighted_km1=10.01,resource_feasible=True)]
        self.assertEqual(rank_rows(rows,CFG)['candidate'],'many')
        rows[0]['resource_feasible']=False
        self.assertEqual(rank_rows(rows,CFG)['candidate'],'few')

    def test_recursive_scalar_proposals_screen_every_resource(self):
        data=dict(atoms=[[a] for a in range(4)],
            atom_resources=[dict(DSP=7),dict(DSP=7),dict(BRAM18=7),dict(BRAM18=7)],
            edges=[((0,1),40),((2,3),40),((1,2),4)])
        original=copy.deepcopy(data)
        groups,detail=recursive_groups(None,data,budget(cap=10,average=4),1,0,splitter=exhaustive_split)
        self.assertEqual(sorted(a for g in groups for a in g),list(range(4)))
        self.assertTrue(budget(cap=10,average=4).audit(data,groups)['valid'])
        self.assertGreaterEqual(detail['split_calls'],2)
        self.assertIsNone(detail['cell_cap']);self.assertIsNone(detail['fixed_k'])
        self.assertEqual(data,original)

    def test_oversized_physical_atom_fails_without_native_solver(self):
        data=dict(atoms=[[0]],atom_resources=[dict(URAM=11)],edges=[])
        with self.assertRaisesRegex(ValueError,'Indivisible'):
            recursive_groups(None,data,budget(),1,0,splitter=lambda *a:self.fail('native called'))

    def test_nonprogressing_and_membership_corrupt_split_fail(self):
        data=dict(atoms=[[0],[1],[2]],atom_resources=[dict(FF=3)]*3,edges=[])
        for children in [[[0,1,2],[]],[[0,1],[1,2]]]:
            with self.assertRaises(ValueError):
                recursive_groups(None,data,budget(5,2),1,0,splitter=lambda *args:children)

    def test_weak_small_modules_remain_despite_spare_capacity(self):
        data=dict(atoms=[[i] for i in range(4)],atom_resources=[dict(FF=1)]*4,
            edges=[((0,1),400),((2,3),400),((1,2),4)])
        groups,detail=selective_merge(data,[[0,1],[2,3]],budget(10,4))
        self.assertEqual(groups,[[0,1],[2,3]])
        self.assertEqual([r['reason'] for r in detail['small_module_exceptions']],['weak_coupling']*2)

    def test_strong_small_modules_merge_unless_resource_forbids(self):
        data=dict(atoms=[[0],[1]],atom_resources=[dict(DSP=3)]*2,edges=[((0,1),4)])
        groups,detail=selective_merge(data,[[0],[1]],budget(10,4))
        self.assertEqual(groups,[[0,1]])
        self.assertTrue(detail['history'][0]['small_module_priority'])
        groups,detail=selective_merge(data,[[0],[1]],budget(5,4))
        self.assertEqual(len(groups),2)
        self.assertEqual(detail['small_module_exceptions'][0]['reason'],'resource_budget')

    def test_disconnected_small_module_exception(self):
        d=dict(atoms=[[0],[1]],atom_resources=[dict(FF=1)]*2,edges=[])
        _,info=selective_merge(d,[[0],[1]],budget())
        self.assertEqual(info['small_module_exceptions'][0]['reason'],'no_connected_neighbor')

    def test_local_move_uses_single_die_all_resource_check(self):
        d=fixture();d['atom_resources'][1]=dict(LUTMEM=3);d['atom_resources'][2]=dict(LUTMEM=3)
        legacy=OriginalIndex(d,[[0,1],[2,3]],[])
        new=OriginalIndex(d,[[0,1],[2,3]],[],resource_fits=budget(5).fits)
        self.assertIsNotNone(legacy.proposal([1],1))
        self.assertIsNone(new.proposal([1],1))

    def test_core_projection_weight_and_original_cut_separate(self):
        from improve import soft_edges
        cores=[dict(atoms=[0,1,2],internal_weight=100)]
        projected=projected_core_edges(cores,[[0,1],[2]],CFG)
        self.assertEqual(projected,[((0,1),soft_edges(cores,.1)[0][1])])
        self.assertEqual(projected_core_edges(cores,[[0,1],[2]],dict(CFG,logical_core_weight=0)),[])

    def test_real_u250_confirmed_caps(self):
        path=SOURCE.parent.parent/'reports/getrf_n512_u256_partition_floorplan_20260923_01/result/cr.tsv'
        if not path.exists():self.skipTest('Local U250 table not present')
        profile=profile_from_cr_table(path,RATIOS);b=Budget(profile)
        self.assertEqual(profile['clock_regions'],128)
        self.assertEqual(b.caps[0]['DSP'],2150)
        self.assertEqual(b.caps[0]['BRAM18'],940)
        self.assertEqual(b.caps[0]['URAM'],320)
        self.assertEqual(b.average['LUT'],9450)


class PipelineTests(unittest.TestCase):
    def test_generate_select_export_never_builds_physical_model(self):
        from improve import digest
        from structure_pipeline import generate,evaluate
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);run=root/'new';old=root/'old'
            (run/'source').mkdir(parents=True);(old/'balanced/candidates/selected').mkdir(parents=True)
            (run/'balanced/candidates/baseline5').mkdir(parents=True)
            (run/'balanced/baseline/final').mkdir(parents=True)
            (run/'balanced/source').symlink_to(run/'source')
            def dump(path,value):path.write_text(json.dumps(value))
            cfg=json.loads((SOURCE/'balanced_config.json').read_text())
            for f in ['structure_config.json','resource_partition_config.json','directed_config.json']:
                shutil.copy2(SOURCE/f,run/'source'/f)
            dump(run/'source/balanced_config.json',cfg)
            dump(run/'request.json',dict(source_run=str(old)))
            d=fixture();d['totals']={'FF':4};d['stats']={}
            d['active_atoms']=[0,1,2]  # isolated atom 3 must still be exported
            with (run/'graph.pkl').open('wb') as stream:pickle.dump(d,stream)
            (run/'balanced/graph.pkl').symlink_to(run/'graph.pkl')
            dump(run/'balanced/binding.json',dict(graph_sha256=digest(run/'graph.pkl'),all_net_weight=2.))
            (run/'cr.tsv').write_text('cr\tx\ty\tslr\tSLICEL\tSLICEM\tDSP\tBRAM36\tURAM\nX0Y0\t0\t0\tSLR0\t1\t0\t0\t0\t0\n')
            dump(run/'balanced/cores.json',[])
            groups=[[0,1],[2,3]]
            dump(run/'balanced/candidates/baseline5/groups.json',groups)
            dump(old/'balanced/candidates/selected/groups.json',groups)
            dump(old/'balanced/selection.json',dict(selected='selected'))
            (root/'dummy.dcp').write_bytes(b'read-only test fixture')
            dump(run/'balanced/baseline/final/modules.json',dict(input_dcp=str(root/'dummy.dcp'),input_sha256=digest(root/'dummy.dcp')))
            with patch('physical_model.build',side_effect=AssertionError('partition used D')), \
                 patch('balanced_regions.evaluate',side_effect=AssertionError('partition chose CRs')), \
                 patch('balanced_regions.initialize',side_effect=AssertionError('partition placed modules')):
                generate(run);evaluate(run)
            selected=run/'balanced/selected'
            meta=json.loads((selected/'modules.json').read_text())
            self.assertEqual(meta['validation']['all_cells'],4)
            self.assertEqual(sum(m['FF'] for m in meta['modules']),4)
            self.assertEqual(meta['partition_objective']['score'],0)
            self.assertFalse((selected/'static_regions.json').exists())
            self.assertFalse((run/'floorplan').exists())
            self.assertTrue(all(m['floorplan_eligible'] for m in meta['modules']))
            # Exercise the actual phase boundary. The native MIP is substituted
            # only here; physical scoring, overlap checks and preparation are real.
            before={p.name:digest(p) for p in selected.iterdir() if p.is_file()}
            def initializer(modules,connections,options,model,device,cfg):
                chosen={m:values[0] for m,values in options.items()}
                return chosen,dict(status='fixture'),{m:[0.]*len(v) for m,v in options.items()}
            from structure_floorplan import prepare
            with patch('balanced_regions.initialize',side_effect=initializer):
                fp=prepare(run)
            self.assertTrue((fp/'input/export/static_regions.json').exists())
            self.assertEqual(before,{p.name:digest(p) for p in selected.iterdir() if p.is_file()})
            binding=json.loads((fp/'binding.json').read_text())
            self.assertEqual(binding['fixed_partition_cost'],meta['partition_objective']['score'])


if __name__=='__main__':unittest.main()
