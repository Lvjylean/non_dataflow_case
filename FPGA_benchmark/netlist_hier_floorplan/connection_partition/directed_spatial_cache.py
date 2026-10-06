"""Migrate boundary directed costs using hash-bound original membership only."""
import csv
import gzip
import json
from pathlib import Path
import pickle

from boundary_directed import SCHEMA, selection
from improve import digest


def load(path):
    return json.loads(path.read_text())


def validate(run):
    spatial=load(run/'directed.json').get('spatial',{})
    if spatial.get('schema')!=SCHEMA:
        raise ValueError('Missing directed boundary cache; rebuild from the original graph.')
    binding=spatial.get('binding',{})
    ids=[m['module_id'] for m in load(run/'input/export/modules.json')['modules']]
    if (binding.get('module_ids')!=ids or spatial.get('module_count')!=len(ids)
            or binding.get('graph_sha256')!=load(run/'binding.json').get('graph_sha256')):
        raise ValueError('Directed boundary graph/module binding mismatch.')
    if binding.get('membership_sha256')!=digest(run/'input/export/leaf_cells.tsv.gz'):
        raise ValueError('Directed boundary membership changed.')


def preflight(previous, cfg, graph_path=None):
    if selection(cfg) != SCHEMA:
        return None
    raw = load(previous/'directed.json')
    if raw.get('spatial',{}).get('schema') == SCHEMA:
        validate(previous)
        return ('reuse',None)
    graph = Path(graph_path).resolve() if graph_path else previous.parent/'graph.pkl'
    expected = load(previous/'binding.json').get('graph_sha256')
    if not expected or not graph.is_file() or digest(graph) != expected:
        raise ValueError('Directed boundary distance needs the bound original graph; supply --graph. Raw pair caches cannot recover anchors.')
    if not (previous/'input/export/leaf_cells.tsv.gz').is_file():
        raise ValueError('Directed boundary distance needs complete frozen leaf membership.')
    return ('build',graph)


def original(run, graph):
    binding = load(run/'binding.json')
    if digest(graph) != binding.get('graph_sha256'):
        raise ValueError('Original graph hash mismatch.')
    with graph.open('rb') as f:
        data = pickle.load(f)
    ids = [m['module_id'] for m in load(run/'input/export/modules.json')['modules']]
    index = {m:i for i,m in enumerate(ids)}; owner = []
    with gzip.open(run/'input/export/leaf_cells.tsv.gz','rt') as f:
        for i,row in enumerate(csv.DictReader(f,delimiter='\t')):
            if i >= len(data['cells']) or any(row[k] != data['cells'][i][k] for k in
                    ('cell_id','cell_name','primitive','original_hierarchy')):
                raise ValueError('Original graph and frozen leaf identities differ.')
            owner.append(index.get(row['module_id'],-1))
    if len(owner) != len(data['cells']):
        raise ValueError('Incomplete frozen membership.')
    labels = []
    for cells in data['atoms']:
        values = {owner[c] for c in cells}
        if len(values)!=1 or -1 in values:
            raise ValueError('Frozen membership splits/unowns an original atom.')
        labels.append(values.pop())
    return data,labels,ids


def prepare_cached(run, prepared, cfg):
    if prepared is None or prepared[0]=='reuse':
        return
    from boundary_hyper import lift
    data,labels,ids = original(run,prepared[1])
    _,_,spatial = lift(data,labels,len(ids),cfg.get('boundary_frontier_max_entries',10000000),with_directed=True)
    spatial['binding'] = dict(graph_sha256=digest(prepared[1]),
        membership_sha256=digest(run/'input/export/leaf_cells.tsv.gz'),module_ids=ids)
    raw = load(run/'directed.json');raw['spatial'] = spatial
    (run/'directed.json').write_text(json.dumps(raw,indent=2)+'\n')
