"""Prepare a small immutable model from the existing graph, without Vivado."""
import gc
import gzip
import csv
import hashlib
import json
import pickle
import shutil
import sys
from pathlib import Path

from balanced_physical import NetModel
from improve import labels_for
from static_regions import load_device
from timing_feedback import build_feedback


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for part in iter(lambda:f.read(8*1024*1024),b''):h.update(part)
    return h.hexdigest()


def prepare(run):
    previous=Path('/Projects/jinyang/workspace/non_dataflow_crossSLR/case/experiment/trtrs_balanced_modules_20260918_E2RZFrs6')
    diag=Path('/Projects/jinyang/workspace/non_dataflow_crossSLR/case/experiment/trtrs_modules11_timing_diag_20260919_b7s1drfy')
    export=previous/'alternatives/slr_emphasis'
    binding=json.loads((previous/'binding.json').read_text())
    assert sha(previous/'graph.pkl')==binding['graph_sha256']
    assert sha(previous/'cr.tsv')==binding['device_sha256']
    cfg=json.loads((run/'source/timing_floorplan_config.json').read_text())
    shutil.copytree(export,run/'input/export')
    shutil.copy2(previous/'cr.tsv',run/'input/cr.tsv')
    shutil.copy2(diag/'binding.json',run/'input/timing_binding.json')
    meta=json.loads((export/'modules.json').read_text())
    assert [m['module_id'] for m in meta['modules']]==[f'S{i:02d}' for i in range(11)]
    groups=json.loads((previous/'candidates'/meta['selected_candidate']/'groups.json').read_text())
    with (previous/'graph.pkl').open('rb') as f:data=pickle.load(f)
    labels=labels_for(data,groups)
    count=0
    with gzip.open(export/'leaf_cells.tsv.gz','rt') as f:
        for c,row in enumerate(csv.DictReader(f,delimiter='\t')):
            assert row['cell_id']==f'c{c}' and row['cell_name']==data['cells'][c]['cell_name']
            a=data['atom_of'][c]
            if a>=0:assert row['module_id']==f'S{labels[a]:02d}'
            count+=1
    assert count==len(data['cells'])
    device=load_device(previous/'cr.tsv')
    netmodel=NetModel(data,labels,11,device)
    feedback=build_feedback(data,labels,diag,cfg)
    (run/'feedback.json').write_text(json.dumps(feedback,indent=2)+'\n')
    with (run/'netmodel.pkl').open('wb') as f:pickle.dump(netmodel,f)
    files={str(p):sha(p) for p in sorted(export.iterdir()) if p.is_file()}
    files[str(previous/'graph.pkl')]=binding['graph_sha256']
    files[str(previous/'cr.tsv')]=binding['device_sha256']
    for name in ['native/paths.tsv','native/cells.tsv','binding.json','complete.json']:
        files[str(diag/name)]=sha(diag/name)
    result=dict(previous=str(previous),diagnostic=str(diag),input_export=str(export),
        graph_sha256=binding['graph_sha256'],post_opt_dcp=binding['input_dcp'],post_opt_sha256=binding['input_sha256'],
        timing_binding=json.loads((diag/'binding.json').read_text()),immutable_files=files,
        total_leaf_cells=count,logical_cells=sum(m['cells'] for m in meta['modules']),module_count=11,
        constants_and_core_cost=meta['metrics'],all_net_weight=binding['all_net_weight'],
        normalized=False,scope='Fixed-membership static floorplan; no new Vivado/partition/netlist changes')
    (run/'binding.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(stage='prepared',coverage=feedback['coverage'],patterns=len(netmodel.patterns))),flush=True)


if __name__=='__main__':prepare(Path(sys.argv[1]))
