"""Bind structural path topology to the original graph and frozen membership."""
import csv
import gzip
import json
from pathlib import Path
import pickle
import shutil

from cumulative_paths import SCHEMA, settings, topology
from improve import digest

FILES=('path_topology.pkl','path_binding.json','path_coverage.json')


def load(path):return json.loads(Path(path).read_text())
def dump(path,value):Path(path).write_text(json.dumps(value,indent=2)+'\n')


def write(run,data,labels,ids,graph_sha256,macro_timing=None,topology_model=None):
    if topology_model is None:
        cfg=settings(load(run/'source/directed_config.json'))
        topology_model=cfg['topology_model'] if cfg else 'ff_cell_v1'
    metadata=None
    if topology_model=='macro_timing_v2' and macro_timing is not None:
        from macro_timing import read as read_macros
        metadata=read_macros(macro_timing,graph_sha256,load(run/'binding.json').get('input_sha256'))
    graph=topology(data,labels,ids,metadata,topology_model)
    with (run/FILES[0]).open('xb') as f:pickle.dump(graph,f,protocol=4)
    dump(run/'path_binding.json',dict(schema=SCHEMA,topology_model=topology_model,graph_sha256=graph_sha256,
        macro_timing_binding=graph.get('macro_binding'),
        membership_sha256=digest(run/'input/export/leaf_cells.tsv.gz'),module_ids=ids,
        topology_sha256=digest(run/'path_topology.pkl'),
        source='Original post-opt cell connectivity; no routed timing report required.'))
    dump(run/'path_coverage.json',graph['coverage'])
    return graph


def read(run):
    binding=load(run/'path_binding.json');parent=load(run/'binding.json')
    ids=[m['module_id'] for m in load(run/'input/export/modules.json')['modules']]
    if binding.get('schema')!=SCHEMA or binding['module_ids']!=ids:
        raise ValueError('Cumulative path cache schema/module IDs mismatch')
    if binding['graph_sha256']!=parent.get('graph_sha256'):
        raise ValueError('Cumulative path cache is not bound to the original graph')
    if binding['membership_sha256']!=digest(run/'input/export/leaf_cells.tsv.gz'):
        raise ValueError('Cumulative path cache membership changed')
    if binding['topology_sha256']!=digest(run/'path_topology.pkl'):
        raise ValueError('Cumulative path topology hash mismatch')
    with (run/'path_topology.pkl').open('rb') as f:graph=pickle.load(f)
    if graph['schema']!=SCHEMA or graph['module_ids']!=ids:
        raise ValueError('Cumulative path payload mismatch')
    if graph.get('topology_model','ff_cell_v1')!=binding.get('topology_model','ff_cell_v1'):
        raise ValueError('Cumulative topology model binding mismatch')
    if graph.get('macro_binding')!=binding.get('macro_timing_binding'):
        raise ValueError('Cumulative macro metadata binding mismatch')
    if graph.get('macro_binding') and graph['macro_binding'].get('input_sha256')!=parent.get('input_sha256'):
        raise ValueError('Cumulative macro metadata DCP mismatch')
    return graph


def preflight(previous,cfg,graph_path=None,macro_timing=None):
    """Check prerequisites before creating a new cache-only run."""
    opts=settings(cfg)
    if not opts:return None
    if (previous/'path_binding.json').exists():
        cached=read(previous)
        if cached.get('topology_model','ff_cell_v1')==opts['topology_model']:
            return ('reuse',None,None,opts['topology_model'])
    path=Path(graph_path).resolve() if graph_path else previous.parent/'graph.pkl'
    expected=load(previous/'binding.json').get('graph_sha256')
    if not expected or not path.is_file() or digest(path)!=expected:
        raise ValueError('Cumulative paths need a graph-bound topology cache or matching original '
                         'graph.pkl; supply --graph. Pair-only caches cannot recover same-cycle paths.')
    if not (previous/'input/export/leaf_cells.tsv.gz').is_file():
        raise ValueError('Cumulative paths need the complete frozen leaf membership')
    metadata=Path(macro_timing).resolve() if macro_timing else path.parent/'macro_timing'
    if not metadata.exists():metadata=None
    if opts['topology_model']=='macro_timing_v2':
        from macro_timing import read as read_macros, macros
        if metadata:read_macros(metadata,expected,load(previous/'binding.json').get('input_sha256'))
        else:
            with path.open('rb') as f:data=pickle.load(f)
            if macros(data):raise ValueError('RAM/DSP cumulative paths require --macro-timing from the original post-opt DCP')
    return ('build',path,metadata,opts['topology_model'])


def prepare_cached(run,previous,prepared):
    if prepared is None:return
    mode,path,metadata,topology_model=prepared
    if mode=='reuse':
        for name in FILES:shutil.copy2(previous/name,run/name)
        read(run);return
    with path.open('rb') as f:data=pickle.load(f)
    ids=[m['module_id'] for m in load(run/'input/export/modules.json')['modules']];index={m:i for i,m in enumerate(ids)}
    owners=[]
    with gzip.open(run/'input/export/leaf_cells.tsv.gz','rt') as f:
        for i,row in enumerate(csv.DictReader(f,delimiter='\t')):
            if i>=len(data['cells']) or any(row[k]!=data['cells'][i][k] for k in
                    ('cell_id','cell_name','primitive','original_hierarchy')):
                raise ValueError('Original graph and frozen leaf identities differ')
            owners.append(index.get(row['module_id'],-1))
    if len(owners)!=len(data['cells']):raise ValueError('Incomplete frozen leaf membership')
    labels=[]
    for cells in data['atoms']:
        values={owners[c] for c in cells}
        if len(values)!=1 or -1 in values:raise ValueError('Frozen membership splits/unowns a physical atom')
        labels.append(values.pop())
    write(run,data,labels,ids,digest(path),metadata,topology_model)
