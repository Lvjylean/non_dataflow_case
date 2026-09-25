"""Positive, ambiguous and adversarial local-chain/protection regressions."""
import copy
import gzip
import json
import pickle
import shutil
from collections import Counter
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from joint_discovery import discover_joint
from joint_units import (export_protection, integrity, load_protection,
                         protection_units, require_intact)
from resource_partition import rank_rows
from structure_frontend import contract, cut_metrics, expand, label_groups
from structure_refine import OriginalIndex, refine


def fixture():
    cells, nets, operators = [], [], []
    def cell(name, primitive):
        i=len(cells)
        cells.append(dict(cell_name=name,cell_id=f'c{i}',primitive=primitive,
                          original_hierarchy=name.rpartition('/')[0] or 'TOP'))
        return i
    bank=cell('storage/wrapper/ram','URAM288')
    first=[cell(f'top/compute/inner/op_a/r{i}','DSP48E2' if i==0 else 'FDRE') for i in range(8)]
    second=[cell(f'top/compute/inner/op_b/r{i}','DSP48E2' if i==0 else 'FDRE') for i in range(8)]
    before=[cell(f'top/compute/wrapper_ff{i}','FDRE') for i in range(8)]
    middle=[cell(f'top/compute/inner/mid_ff{i}','FDRE') for i in range(8)]
    cell('unrelated','FDRE')
    for i in range(8):
        for d,s in [(bank,before[i]),(before[i],first[i]),(first[i],middle[i]),(middle[i],second[i])]:
            nets.append((f'n{len(nets)}',d,[s],4))
    for name,aa in [('top/compute/inner/op_a',first),('top/compute/inner/op_b',second)]:
        operators.append(dict(hierarchy=name,atoms=aa))
    resources=[{'URAM':1} if c['primitive']=='URAM288' else {'DSP':1} if c['primitive']=='DSP48E2' else {'FF':1} for c in cells]
    d=dict(cells=cells,atoms=[[i] for i in range(len(cells))],atom_of=list(range(len(cells))),
           nets=nets,edges=[((d,*ss),w) for _,d,ss,w in nets],atom_resources=resources)
    return d,operators


class DiscoveryTests(unittest.TestCase):
    def test_actual_generate_rank_deliver_and_floorplan_gate_with_joint(self):
        from improve import digest
        from structure_pipeline import generate,evaluate
        from balanced_deliver import deliver
        from structure_floorplan import prepare
        source=Path(__file__).resolve().parent
        d,ops=fixture()
        d.update(totals=dict(sum((Counter(q) for q in d['atom_resources']),Counter())),stats={},
                 active_atoms=list(range(len(d['atoms']))))
        for op in ops:
            op['resources']=dict(sum((Counter(d['atom_resources'][a]) for a in op['atoms']),Counter()))
            op['cells']=len(op['atoms'])
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);run=root/'run';old=root/'old'
            (run/'source').mkdir(parents=True)
            for f in ['structure_config.json','resource_partition_config.json','balanced_config.json','directed_config.json']:
                shutil.copy2(source/f,run/'source'/f)
            def dump(path,value):path.write_text(json.dumps(value))
            cfg=json.loads((run/'source/structure_config.json').read_text());cfg['seeds']=[0]
            dump(run/'source/structure_config.json',cfg)
            (run/'balanced/candidates/baseline5').mkdir(parents=True)
            (run/'balanced/baseline/final').mkdir(parents=True)
            (run/'balanced/source').symlink_to(run/'source')
            (old/'balanced/candidates/selected').mkdir(parents=True)
            pickle.dump(d,(run/'graph.pkl').open('wb'))
            (run/'balanced/graph.pkl').symlink_to(run/'graph.pkl')
            dump(run/'balanced/binding.json',dict(graph_sha256=digest(run/'graph.pkl'),all_net_weight=32))
            dump(run/'balanced/cores.json',[])
            broken=[[0,33],list(range(1,33))]
            dump(run/'balanced/candidates/baseline5/groups.json',broken)
            dump(old/'balanced/candidates/selected/groups.json',broken)
            dump(old/'balanced/selection.json',dict(selected='selected'))
            dump(run/'request.json',dict(source_run=str(old)))
            (run/'cr.tsv').write_text('cr\tx\ty\tslr\tSLICEL\tSLICEM\tDSP\tBRAM36\tURAM\nX0Y0\t0\t0\tSLR0\t100\t0\t10\t8\t8\n')
            (root/'dummy.dcp').write_bytes(b'fixture')
            dump(run/'balanced/baseline/final/modules.json',dict(input_dcp=str(root/'dummy.dcp'),input_sha256=digest(root/'dummy.dcp')))
            with patch('resource_pipeline.discover',return_value=(ops,[])), \
                 patch('physical_model.build',side_effect=AssertionError('partition used physical model')):
                generate(run);evaluate(run)
            meta=json.loads((run/'balanced/selected/modules.json').read_text())
            self.assertEqual(meta['protection']['split_units'],0)
            self.assertEqual(len(json.loads((run/'balanced/selected/joint_chains.json').read_text())['chains']),1)
            comparisons=json.loads((run/'balanced/comparison.json').read_text())
            self.assertFalse(next(r for r in comparisons if r['candidate']=='control_current')['protection_feasible'])
            self.assertFalse((run/'balanced/candidates/control_candidate').exists())
            with self.assertRaisesRegex(ValueError,'delivery admission'):
                deliver(run/'balanced','control_current','must_not_export','S')
            self.assertFalse((run/'balanced/must_not_export').exists())
            selected=meta['selected_candidate']
            selected_groups=json.loads((run/'balanced/candidates'/selected/'groups.json').read_text())
            dump(run/'balanced/candidates'/selected/'groups.json',broken)
            with self.assertRaisesRegex(ValueError,'floorplan input'):
                prepare(run)
            self.assertFalse((run/'floorplan').exists())
            dump(run/'balanced/candidates'/selected/'groups.json',selected_groups)
            def initializer(modules,connections,options,model,device,cfg):
                chosen={m:values[0] for m,values in options.items()}
                return chosen,dict(status='fixture'),{m:[0.]*len(v) for m,v in options.items()}
            with patch('balanced_regions.initialize',side_effect=initializer):
                fp=prepare(run)
            for name in ['joint_chains.json','joint_chain_cells.tsv.gz']:
                self.assertEqual((fp/'input/export'/name).read_bytes(),(run/'balanced/selected'/name).read_bytes())

    def test_full_memory_chain_wrapper_ff_and_exact_contraction(self):
        d,ops=fixture(); original=copy.deepcopy(d)
        joint,audit=discover_joint(d,ops,{},lambda q:True)
        self.assertEqual(len(joint),1)
        self.assertEqual(joint[0]['atoms'],list(range(33)))
        self.assertEqual(joint[0]['resources'],dict(URAM=1,DSP=2,FF=30))
        self.assertEqual(joint[0]['discovery']['bridge_atoms'],16)
        protected=protection_units(ops,joint)
        coarse,mapping,_=contract(d,protected)
        groups=expand([[0],[1]],mapping,len(d['atoms']))
        self.assertEqual(cut_metrics(coarse['edges'],[0,1]),cut_metrics(d['edges'],label_groups(groups,34)))
        self.assertEqual(d,original)

    def test_controls_high_fanout_and_one_bit_broadcast_do_not_form_chain(self):
        for kind in ['control','fanout','one_bit']:
            d,ops=fixture()
            if kind=='control':
                d['nets']=[(n,a,ss,1) for n,a,ss,w in d['nets']]
            elif kind=='fanout':
                d['nets']=[(n,a,ss*65,w) for n,a,ss,w in d['nets']]
            else:
                receivers=[ss[0] for n,a,ss,w in d['nets'] if a==0]
                d['nets']=[(n,a,ss,w) for n,a,ss,w in d['nets'] if a!=0]+[('broadcast',0,receivers,4)]
            self.assertFalse(discover_joint(d,ops,{},lambda q:True)[0],kind)

    def test_multibank_mux_is_a_boundary_and_not_a_chain(self):
        d,ops=fixture()
        # Each operand-input bridge now combines memory and external data.
        for i in range(17,25):
            d['cells'][i]['primitive']='LUT2'
            d['nets'].append(('combine'+str(i),33,[i],4))
        self.assertFalse(discover_joint(d,ops,{},lambda q:True)[0])

    def test_hop_resource_and_disabled_gates(self):
        d,ops=fixture()
        self.assertFalse(discover_joint(d,ops,dict(max_bridge_hops=1,min_data_nets=9),lambda q:True)[0])
        joint,audit=discover_joint(d,ops,{},lambda q:q.get('URAM',0)==0)
        self.assertFalse(joint)
        self.assertIn('single_die_resource_budget',audit['chains'][0]['rejection_reasons'])
        self.assertFalse(discover_joint(d,ops,dict(enabled=False),lambda q:True)[0])

    def test_shared_memory_with_two_real_compute_consumers_is_not_bound(self):
        d,ops=fixture()
        # Duplicate the local computation, retaining the one shared bank.
        source=copy.deepcopy(d)
        offset=len(d['atoms'])-1
        for c in source['cells'][1:]:
            row=dict(c,cell_name=c['cell_name'].replace('top/compute','top/other'))
            d['cells'].append(row)
        d['atoms']=[[i] for i in range(len(d['cells']))];d['atom_of']=list(range(len(d['cells'])))
        d['atom_resources']+=copy.deepcopy(source['atom_resources'][1:])
        for n,a,ss,w in source['nets']:
            d['nets'].append(('copy'+n,0 if a==0 else a+offset,[s+offset for s in ss],w))
        ops+= [dict(hierarchy=u['hierarchy'].replace('top/compute','top/other'),atoms=[a+offset for a in u['atoms']]) for u in list(ops)]
        for cfg in [dict(max_scope_cells=40),{}]:
            self.assertFalse(discover_joint(d,ops,cfg,lambda q:True)[0])

    def test_crossing_physical_atom_and_long_or_weak_corridor_rejected(self):
        d,ops=fixture()
        d['atoms'][17].append(33);d['atoms'].pop();d['atom_of'][33]=17
        d['atom_resources'][17]['FF']+=1;d['atom_resources'].pop()
        self.assertFalse(discover_joint(d,ops,{},lambda q:True)[0])
        d,ops=fixture()
        d['cells'][17]['primitive']='LUT2'
        d['nets'].append(('external_data','PORT:in',[17],4))
        # One of eight memory lanes becomes ambiguous: below the width gate.
        self.assertFalse(discover_joint(d,ops,{},lambda q:True)[0])

    def test_refiner_and_ranking_cannot_admit_or_split_joint(self):
        d,ops=fixture();joint,_=discover_joint(d,ops,{},lambda q:True)
        units=protection_units(ops,joint)
        groups=[list(range(33)),[33]]
        index=OriginalIndex(d,groups,units,resource_fits=lambda q:True)
        self.assertIsNone(index.proposal([0],1))
        cfg=dict(require_intact_units=True,local_search_seconds=1,local_max_moves=10,loose_module_connected_fraction=.9)
        bad=[[0,33],list(range(1,33))]
        with self.assertRaisesRegex(ValueError,'local refinement input'):
            refine(d,bad,units,cfg,resource_fits=lambda q:True)
        result,_=refine(d,groups,units,cfg,resource_fits=lambda q:True)
        self.assertTrue(integrity(label_groups(result,34),units)['valid'])
        rows=[dict(candidate='broken_cheaper',resource_feasible=True,protection_feasible=False,weighted_km1=0,logical_core_loss=0),
              dict(candidate='intact',resource_feasible=True,protection_feasible=True,weighted_km1=100,logical_core_loss=0)]
        self.assertEqual(rank_rows(rows,dict(cut_weight=1,logical_core_weight=1))['candidate'],'intact')

    def test_export_ids_and_fail_closed_bundle(self):
        d,ops=fixture();joint,_=discover_joint(d,ops,{},lambda q:True);units=protection_units(ops,joint)
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)
            export_protection(p,d,[0]*33+[1],units,joint,['S00','S01'],{})
            with gzip.open(p/'joint_chain_cells.tsv.gz','rt') as f:
                self.assertEqual(len(f.readlines()),34)
            with self.assertRaisesRegex(ValueError,'final export'):
                export_protection(p,d,[1]+[0]*33,units,joint,['S00','S01'],{})
            (p/'source').mkdir()
            (p/'source/resource_partition_config.json').write_text('{"joint_chains":{"enabled":true}}')
            with self.assertRaisesRegex(ValueError,'bundle is missing'):load_protection(p)


if __name__=='__main__':unittest.main()
