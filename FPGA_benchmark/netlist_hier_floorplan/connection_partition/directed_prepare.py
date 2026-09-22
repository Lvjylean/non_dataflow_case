"""Reuse the immutable graph and exact eleven-module membership; no Vivado."""
import csv
import gzip
import hashlib
import json
import pickle
import shutil
import sys
from collections import Counter,defaultdict
from pathlib import Path
from balanced_physical import atom_resource
from static_regions import RESOURCES


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(8*1024*1024),b''):h.update(b)
    return h.hexdigest()


def prepare(run):
    root=Path('/Projects/jinyang/workspace/non_dataflow_crossSLR/case/experiment')
    previous=root/'trtrs_modules11_timing_floorplan_20260919_sa23o5vf'
    balanced=root/'trtrs_balanced_modules_20260918_E2RZFrs6'
    graph=balanced/'graph.pkl'
    binding=json.loads((previous/'binding.json').read_text())
    assert sha(graph)==binding['graph_sha256']
    run.joinpath('input').mkdir(exist_ok=True)
    shutil.copytree(previous/'export',run/'input/export')
    shutil.copy2(previous/'input/cr.tsv',run/'input/cr.tsv')
    shutil.copy2(previous/'input/export/static_regions.json',run/'input/original_regions.json')
    shutil.copy2(previous/'netmodel.pkl',run/'netmodel.pkl')
    meta=json.loads((run/'input/export/modules.json').read_text())
    assert [m['module_id'] for m in meta['modules']]==[f'S{i:02d}' for i in range(11)]
    with graph.open('rb') as f:data=pickle.load(f)
    labels=[-1]*len(data['atoms']);cell_modules=[]
    with gzip.open(run/'input/export/leaf_cells.tsv.gz','rt') as f:
        for i,r in enumerate(csv.DictReader(f,delimiter='\t')):
            assert r['cell_id']==f'c{i}' and r['cell_name']==data['cells'][i]['cell_name']
            cell_modules.append(r['module_id']);a=data['atom_of'][i]
            if a>=0:
                label=int(r['module_id'][1:]);assert labels[a] in (-1,label);labels[a]=label
    assert len(cell_modules)==len(data['cells']) and min(labels)>=0
    slots=[labels[i]*len(RESOURCES)+RESOURCES.index(atom_resource(r)) for i,r in enumerate(data['atom_resources'])]
    weights=Counter();counts=Counter();coverage=Counter();family={}
    def new_family():return dict(nets=0,sink_pins=0,same_atom_pins=0,counts=Counter())
    for name in ['matA_write_64','matB_read_all','matB_read_bit62']:family[name]=new_family()
    for net_id,driver,sinks,weight4 in data['nets']:
        coverage['signal_nets']+=1;coverage['signal_sink_pins']+=len(sinks)
        weight=weight4/4;modeled=False
        if not isinstance(driver,int):
            coverage['unlocated_port_source_pins']+=len(sinks);continue
        a=data['atom_of'][driver]
        if a<0:
            coverage['unlocated_infrastructure_source_pins']+=len(sinks);continue
        name=data['cells'][driver]['cell_name'];families=[]
        if 'bitcast_ln109_reg_9585_reg[' in name:families.append('matA_write_64')
        if name=='gmem1_m_axi_U/load_unit/buff_rdata/U_fifo_mem/mem_reg':families.append('matB_read_all')
        if net_id=='n509453':families.append('matB_read_bit62')
        for fam in families:family[fam]['nets']+=1
        for sink in sinks:
            if not isinstance(sink,int):coverage['unlocated_port_sink_pins']+=1;continue
            b=data['atom_of'][sink]
            if b<0:coverage['unlocated_infrastructure_sink_pins']+=1;continue
            modeled=True;coverage['modeled_sink_pins']+=1
            coverage['data_pins' if weight4==4 else 'control_pins']+=1
            for fam in families:family[fam]['sink_pins']+=1
            if a==b:
                coverage['same_atom_pins']+=1
                for fam in families:family[fam]['same_atom_pins']+=1
                continue
            pair=(slots[a],slots[b]);weights[pair]+=weight;counts[pair]+=1
            coverage['distinct_atom_pins']+=1
            coverage['internal_module_pins' if labels[a]==labels[b] else 'inter_module_pins']+=1
            for fam in families:family[fam]['counts'][pair]+=1
        if modeled:coverage['nets_with_modeled_pins']+=1
    assert coverage['modeled_sink_pins']==coverage['same_atom_pins']+coverage['distinct_atom_pins']
    assert coverage['signal_sink_pins']==coverage['modeled_sink_pins']+sum(coverage[k] for k in [
        'unlocated_port_source_pins','unlocated_port_sink_pins','unlocated_infrastructure_source_pins','unlocated_infrastructure_sink_pins'])
    for name,f in family.items():
        f['pairs']=[dict(source=a,sink=b,pins=n) for (a,b),n in sorted(f.pop('counts').items())]
    assert family['matA_write_64']['nets']==64 and family['matA_write_64']['sink_pins']==32768
    assert family['matB_read_bit62']['sink_pins']==1024
    result=dict(module_count=11,pairs=[dict(source=a,sink=b,weight=w,pins=counts[a,b]) for (a,b),w in sorted(weights.items())],
        coverage=dict(coverage),families=family,original_inventory=data['stats'],
        semantics='Original sink-pin multiplicity; all modeled directions retained. Same physical atom has zero length. No path accumulation or sampled criticality.',
        limitations=['Ports and unassigned infrastructure lack candidate positions; excluded branch counts are explicit.',
            'The original graph already excludes constant and CLOCK-classified nets; its legacy CLOCK classification includes BUFG-driven infrastructure, not a new true-clock audit.',
            'Positions of different atoms are independent capacity-weighted estimates, not routed coordinates.',
            'The model counts communication demand, not replicated physical SLL wires.'])
    (run/'directed.json').write_text(json.dumps(result,indent=2)+'\n')
    original_files={str(p):sha(p) for p in (previous/'export').iterdir() if p.is_file()}
    for p in [graph,previous/'input/cr.tsv',previous/'netmodel.pkl',previous/'input/export/static_regions.json']:
        original_files[str(p)]=sha(p)
    output=dict(previous=str(previous),input_dcp=meta['input_dcp'],input_sha256=meta['input_sha256'],
        graph=str(graph),graph_sha256=binding['graph_sha256'],immutable_files=original_files,
        total_leaf_cells=len(cell_modules),logical_cells=sum(m['cells'] for m in meta['modules']),module_count=11,
        fixed_partition_cost=json.loads((run/'input/original_regions.json').read_text())['objective']-json.loads((run/'input/original_regions.json').read_text())['components']['physical_cost'],
        scope='Fixed11 directed static floorplan; no partition, new STA, netlist changes, fanout or P&R.')
    (run/'binding.json').write_text(json.dumps(output,indent=2)+'\n')
    print(json.dumps(dict(stage='prepared',coverage=dict(coverage),role_pairs=len(weights),families={k:{a:v for a,v in f.items() if a!='pairs'} for k,f in family.items()})),flush=True)


if __name__=='__main__':prepare(Path(sys.argv[1]))
