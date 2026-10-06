"""Bind native RAM/DSP pin timing arcs to the unchanged post-opt cell graph.

Only macro-internal pins are expanded. Ordinary LUT/CARRY/MUX nodes retain
conservative cell-level arcs. No delay, placement or routed feedback is used.
"""
import argparse
from collections import Counter, defaultdict, deque
import csv
import json
import itertools
from pathlib import Path
import pickle
import re

import numpy as np

from control_path_cost import COMB, REG
from improve import digest

MODEL='macro_timing_v2'
SCHEMA='postopt-macro-timing-v1'
FAMILY=re.compile(r'^(?:URAM|RAMB|DSP48)')


def macros(data):return {i for i,c in enumerate(data['cells']) if FAMILY.match(c['primitive'])}
def dump(path,value):path.write_text(json.dumps(value,indent=2)+'\n')


def compress_arcs(records):
    """Exact zero-distance elimination inside a macro, stopping at every state.

    Output frontiers with equal input dependencies share a factor node. This
    preserves max-plus propagation without retaining thousands of DSP bit arcs.
    """
    edges={(r['from_pin'],r['to_pin']) for r in records}
    nodes={p for edge in edges for p in edge};state='@state'
    external=lambda p:p!=state and '/' not in p
    inputs=sorted({a for a,b in edges if external(a)})
    outputs={b for a,b in edges if external(b)}
    seeds=inputs+([state] if state in nodes else [])
    front={v:0 for v in nodes}
    for i,v in enumerate(seeds):front[v]=1<<i
    indegree=Counter();adj=defaultdict(list)
    for a,b in edges:
        if b==state:continue
        adj[a].append(b)
        if a!=state:indegree[b]+=1
    queue=deque(sorted(v for v in nodes if v!=state and not indegree[v]));seen=0
    for b in adj[state]:front[b]|=front[state]
    while queue:
        a=queue.popleft();seen+=1
        for b in adj[a]:
            front[b]|=front[a];indegree[b]-=1
            if indegree[b]==0:queue.append(b)
    if seen!=len(nodes-{state}):raise ValueError('Combinational cycle in native macro graph')
    targets=defaultdict(list)
    for b in sorted(outputs):
        if front[b]:targets[front[b]].append(b)
    capture=0
    for a,b in edges:
        if b==state:capture|=front[a]
    if capture:targets[capture].append(state)
    result=set()
    for j,(bits,ends) in enumerate(sorted(targets.items())):
        starts=[v for i,v in enumerate(seeds) if bits&(1<<i)]
        if len(starts)>1 and len(ends)>1:
            factor=f'@join{j}'
            result.update((a,factor) for a in starts)
            result.update((factor,b) for b in ends)
        else:result.update((a,b) for a in starts for b in ends)
    return result,len(edges)


def native_groups(native):
    """Stream one macro at a time from either normalized or bulk native output."""
    if not (native/'raw_timing.tsv').exists():
        with (native/'arcs.tsv').open() as f:
            for cid,rows in itertools.groupby(csv.DictReader(f,delimiter='\t'),key=lambda r:r['cell_id']):
                yield cid,list(rows)
        return
    def groups(name):
        with (native/name).open() as f:
            for cid,rows in itertools.groupby(csv.DictReader(f,delimiter='\t'),key=lambda r:r['cell_id']):
                yield cid,list(rows)
    wires=iter(groups('arcs.tsv'));wire=next(wires,None)
    pins=iter(groups('pins.tsv'));raw=iter(groups('raw_timing.tsv'))
    for cid,records in raw:
        pid,pp=next(pins)
        if pid!=cid:raise ValueError('Native macro pin order mismatch')
        dirs={p['pin']:p['direction'] for p in pp}
        clocks={p['pin']:p['clock'] in {'1','true','TRUE'} for p in pp}
        rows=[]
        if wire and wire[0]==cid:rows.extend(wire[1]);wire=next(wires,None)
        for record in records:
            match=re.fullmatch(r'(.*) --> (.*) \[([^]]+)\] *',record['arc'].strip('{} '))
            if not match:raise ValueError('Unrecognized native timing arc: '+record['arc'])
            a,b,kind=match.groups()
            if a not in clocks or b not in clocks:raise ValueError('Nonlocal native timing arc')
            if kind in {'setup','hold','recovery','removal'} and clocks[a] and not clocks[b] and dirs[b]=='IN':
                k,a,b='capture',b,'@state'
            elif clocks[a] and not clocks[b] and dirs[b]=='OUT':k,a='launch','@state'
            elif kind=='combinational' and not clocks[a] and not clocks[b] and dirs[a]=='IN' and dirs[b]=='OUT':k='comb'
            else:raise ValueError('Unsupported native timing arc: '+record['arc'])
            rows.append(dict(cell_id=cid,kind=k,from_pin=a,to_pin=b))
        yield cid,rows
    if wire is not None or next(pins,None) is not None:raise ValueError('Unmatched native pin/wire groups')


def compile_overlay(data,native,raw_nets):
    """Exact identities and pin nets are essential; a cell-only cache cannot infer arcs."""
    expected=macros(data);byid={c['cell_id']:i for i,c in enumerate(data['cells'])}
    rows=list(csv.DictReader((native/'macros.tsv').open(),delimiter='\t'))
    complete=(native/'complete.txt').read_text().strip()
    if complete!=f'macros={len(rows)}':raise ValueError('Incomplete native macro timing extraction')
    inventory={r['cell_id']:r for r in rows}
    found=set()
    for r in rows:
        i=byid.get(r['cell_id'],-1)
        if i in found or i not in expected or any(r[k]!=data['cells'][i][k] for k in ('cell_name','primitive')):
            raise ValueError('Native macro identity mismatch')
        found.add(i)
    if found!=expected:raise ValueError('Missing native macro cells')
    n=len(data['cells']);pin_nodes={};node_cells=[];states=set();edges=set();counts=Counter()
    def node(c,p):
        if p=='@state':states.add(c);return c
        key=(c,p)
        if key not in pin_nodes:
            pin_nodes[key]=n+len(node_cells);node_cells.append(c)
        return pin_nodes[key]
    seen_cells=set()
    for cid,records in native_groups(native):
        c=byid[cid]
        inv=inventory[cid]
        if 'active_arcs' in inv and len(records)!=int(inv['active_arcs'])+int(inv['wires']):
            raise ValueError('Native macro arc count mismatch: '+cid)
        if c in seen_cells:raise ValueError('Native macro arcs must be grouped by cell')
        seen_cells.add(c)
        for r in records:
            kind=r['kind'];a=r['from_pin'];b=r['to_pin']
            if c not in expected or kind not in {'wire','comb','capture','launch'}:
                raise ValueError('Invalid native macro arc')
            if (a=='@state')!=(kind=='launch') or (b=='@state')!=(kind=='capture'):
                raise ValueError('Malformed macro state boundary')
            counts[kind]+=1
        compressed,unique=compress_arcs(records)
        counts['native_unique_internal_edges']+=unique
        counts['compressed_internal_edges']+=len(compressed)
        for a,b in compressed:edges.add((node(c,a),node(c,b)))
    if seen_cells!=expected:raise ValueError('Missing native macro arcs')
    ordinary={i for i,c in enumerate(data['cells']) if c['primitive'] in REG or COMB.fullmatch(c['primitive'])}
    supported=ordinary|expected
    opaque=Counter();unmodeled=Counter();needed_nets={}
    def token(s):
        if s.startswith('PORT:'):return None,None
        cid,sep,p=s.partition(':')
        if not sep or cid not in byid:raise ValueError('Malformed or unknown raw pin')
        return byid[cid],p
    with raw_nets.open() as f:
        for r in csv.DictReader(f,delimiter='\t'):
            if r['type'].lower() in {'clock','ground','power'}:continue
            drivers=[token(s) for s in r['drivers'].split(',') if s]
            sinks=[token(s) for s in r['sinks'].split(',') if s]
            if not any(c in expected for c,p in drivers+sinks):continue
            if len(drivers)!=1:raise ValueError('Macro pin net is not single-driver')
            a,ap=drivers[0];needed_nets[r['net_id']]=(a,tuple(c for c,p in sinks))
            for b,bp in sinks:
                if a not in expected and b not in expected:continue
                if a is None or b is None:
                    counts['top_port_pins']+=1;continue
                if a not in supported:
                    opaque[data['cells'][a]['primitive']]+=1;continue
                if b not in supported:
                    unmodeled[data['cells'][b]['primitive']]+=1;continue
                aa=node(a,ap) if a in expected else a
                bb=node(b,bp) if b in expected else b
                edges.add((aa,bb));counts['external_wire_pins']+=1
    # The exact old graph net IDs and cell endpoints must agree with the raw pins.
    matched=set()
    for nid,a,sinks,w in data['nets']:
        if nid not in needed_nets:continue
        ra,rs=needed_nets[nid]
        normalize=lambda x:x if isinstance(x,int) else None
        if normalize(a)!=ra or Counter(map(normalize,sinks))!=Counter(rs):
            raise ValueError('Raw pin connectivity differs from original graph: '+nid)
        matched.add(nid)
    if matched!=set(needed_nets):raise ValueError('Raw macro net missing from original graph')
    arr=np.array(sorted(edges),dtype=np.int32).reshape(-1,2)
    return dict(schema=SCHEMA,cell_count=n,macro_cells=sorted(expected),state_cells=sorted(states),
                node_cells=np.asarray(node_cells,dtype=np.int32),edges=arr,pin_nodes=pin_nodes,
                coverage=dict(native_macros=dict(Counter(data['cells'][i]['primitive'] for i in expected)),
                    native_arc_records=dict(counts),native_unique_edges=len(edges),
                    opaque_macro_sources=dict(opaque),unmodeled_macro_sinks=dict(unmodeled)))


def build(graph,native,raw_nets,dcp,output):
    if output.exists():raise ValueError('Refusing to overwrite macro timing cache')
    provenance={r['kind']:r for r in csv.DictReader((native/'input_binding.tsv').open(),delimiter='\t')}
    if provenance['dcp']['sha256']!=digest(dcp):raise ValueError('Native timing extraction belongs to a different DCP')
    with graph.open('rb') as f:data=pickle.load(f)
    overlay=compile_overlay(data,native,raw_nets)
    output.mkdir(parents=True)
    with (output/'macro_timing.pkl').open('xb') as f:pickle.dump(overlay,f,protocol=4)
    dump(output/'binding.json',dict(schema=SCHEMA,graph_sha256=digest(graph),input_sha256=digest(dcp),
        input_dcp=str(dcp),raw_nets_sha256=digest(raw_nets),
        native_files={p.name:digest(p) for p in native.iterdir() if p.is_file()},native_provenance=provenance,
        payload_sha256=digest(output/'macro_timing.pkl'),coverage=overlay['coverage']))


def read(path,graph_sha256,input_sha256=None):
    path=Path(path);binding=json.loads((path/'binding.json').read_text())
    if binding.get('schema')!=SCHEMA or binding.get('graph_sha256')!=graph_sha256:
        raise ValueError('Macro timing cache graph/schema mismatch')
    if input_sha256 and binding.get('input_sha256')!=input_sha256:
        raise ValueError('Macro timing cache DCP mismatch')
    if digest(path/'macro_timing.pkl')!=binding['payload_sha256']:
        raise ValueError('Macro timing cache hash mismatch')
    with (path/'macro_timing.pkl').open('rb') as f:result=pickle.load(f)
    if result['schema']!=SCHEMA:raise ValueError('Macro timing payload schema mismatch')
    return dict(result,binding=binding)


def expanded(model,data,overlay):
    """Native macro pins share their original cell's owner and physical location."""
    expected=macros(data)
    if expected and overlay is None:
        raise ValueError('RAM/DSP cumulative paths require native macro timing metadata; use --macro-timing. '
                         'The old cell-only cache cannot recover registered versus combinational macro arcs.')
    if not expected:
        return model.reg,model.comb,model.launch,model.layers,np.arange(len(data['cells'])),{},{}
    if overlay['cell_count']!=len(data['cells']) or set(overlay['macro_cells'])!=expected:
        raise ValueError('Macro timing cell inventory mismatch')
    node_cells=np.r_[np.arange(len(data['cells']),dtype=np.int32),overlay['node_cells']]
    n=len(node_cells);reg=np.r_[model.reg,np.zeros(len(overlay['node_cells']),dtype=bool)]
    reg[overlay['state_cells']]=True
    comb=np.r_[model.comb,np.ones(len(overlay['node_cells']),dtype=bool)]
    extra=overlay['edges'];launch=np.vstack((np.column_stack(model.launch),extra[reg[extra[:,0]]]))
    old=[np.column_stack(x) for x in model.layers]
    ordinary=np.concatenate(old) if old else np.empty((0,2),dtype=np.int32)
    combinational=np.vstack((ordinary,extra[~reg[extra[:,0]]]))
    incoming=np.bincount(combinational[:,1][comb[combinational[:,1]]],minlength=n)
    adjacency=defaultdict(list)
    for a,b in combinational:adjacency[int(a)].append(int(b))
    queue=np.flatnonzero(comb&(incoming==0)).tolist();layers=[];visited=0
    while queue:
        visited+=len(queue);pairs=[];following=[]
        for a in queue:
            for b in adjacency.get(a,()):
                pairs.append((a,b))
                if comb[b]:
                    incoming[b]-=1
                    if incoming[b]==0:following.append(b)
        if pairs:layers.append(model.arrays(pairs))
        queue=following
    if visited!=int(comb.sum()):
        unresolved=np.flatnonzero(comb&(incoming>0))
        raise ValueError('Combinational cycle in expanded macro graph; unresolved cells '+
                         str(sorted(set(map(int,node_cells[unresolved])))[:20]))
    return reg,comb,(launch[:,0],launch[:,1]),layers,node_cells,overlay['coverage'],overlay['pin_nodes']


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('graph','native','raw-nets','dcp','output'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();build(a.graph,a.native,a.raw_nets,a.dcp,a.output)
