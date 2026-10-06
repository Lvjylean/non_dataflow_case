"""Compare D_hyper at fixed module regions; never run a floorplan search."""
import argparse
import hashlib
import json
from pathlib import Path
import pickle
import time

from boundary_hyper import BoundaryNetModel, independent_spans
from balanced_physical import NetModel
from physical_model import LEGACY
from structure_frontend import label_groups
from static_regions import load_device


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(8*1024*1024),b''):h.update(block)
    return h.hexdigest()


def compare(graph,groups_path,device_path,solution_path,output,slr_weight=None):
    # Pickles must be trusted project caches. No remote files are downloaded.
    if output.exists():raise FileExistsError(output)
    started=time.monotonic()
    with graph.open('rb') as stream:data=pickle.load(stream)
    groups=json.loads(groups_path.read_text())
    if isinstance(groups,dict):groups=groups['groups']
    labels=label_groups(groups,len(data['atoms']))
    solution=json.loads(solution_path.read_text())
    if len(solution['regions'])!=len(groups):raise ValueError('Module count mismatch.')
    chosen={}
    for i,aa in enumerate(groups):
        mid=f'S{i:02d}' if f'S{i:02d}' in solution['regions'] else f'P{i:02d}'
        chosen[f'P{i:02d}']=solution['regions'][mid]
    cfg=solution.get('configuration',{})
    if slr_weight is None:
        if 'slr_distance_weight' not in cfg:
            raise ValueError('Supply --slr-weight for a solution without frozen configuration.')
        slr_weight=cfg['slr_distance_weight']
    device=load_device(device_path)
    old=NetModel(data,labels,len(groups),device).components(chosen,slr_weight)
    model=BoundaryNetModel(data,labels,len(groups),device)
    new=model.components(chosen,slr_weight)
    independent=independent_spans(model,chosen)
    for name,axis in [('x_span','x'),('y_span','y'),('slr_span','slr')]:
        assert abs(new[name]-independent[axis])<=max(1e-6,abs(new[name])*1e-10)
    result=dict(status='PASS',scope='Fixed-layout D_hyper comparison; no search, P&R or timing claim.',
                slr_weight=slr_weight,legacy=old,boundary=new,audit=model.audit,
                independent_spans=independent,seconds=time.monotonic()-started,
                inputs={str(p):sha(p) for p in [graph,groups_path,device_path,solution_path]})
    previous=solution.get('components',{})
    if cfg.get('hypernet_model',LEGACY)==LEGACY and 'J' in previous:
        if abs(old['physical_cost']-previous['physical_cost'])>max(1e-6,abs(old['physical_cost'])*1e-10):
            raise ValueError('Legacy rescore does not match the supplied solution; input binding is inconsistent.')
        weight=cfg.get('hypernet_weight',1.)
        result['J_with_only_D_hyper_changed']=previous['J']+weight*(new['physical_cost']-old['physical_cost'])
        result['remaining_terms_unchanged']=previous['J']-weight*old['physical_cost']
    output.mkdir(parents=True)
    (output/'comparison.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for flag in ['graph','groups','device','solution','output']:
        parser.add_argument('--'+flag,type=Path,required=True)
    parser.add_argument('--slr-weight',type=float)
    a=parser.parse_args()
    result=compare(a.graph,a.groups,a.device,a.solution,a.output,a.slr_weight)
    print(json.dumps({k:result[k] for k in ['status','scope','legacy','boundary','seconds']}))
