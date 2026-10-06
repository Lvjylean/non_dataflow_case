"""Incremental, register-bounded SLR propagation for fixed-membership search.

This is a conservative connectivity proxy, not a delay or slack estimator.
The first release requires one definite SLR per physical core region.
"""
from collections import Counter, OrderedDict
import heapq
import math

import numpy as np

from control_path_cost import PathModel

SCHEMA='cumulative-slr-paths-v1'


def settings(cfg):
    value=cfg.get('cumulative_paths',{})
    if not value.get('enabled',False):return None
    if value.get('schema')!=SCHEMA or value.get('penalty')!='exponential':
        raise ValueError('Unsupported cumulative path model or penalty')
    if value.get('region_policy')!='single_slr':
        raise ValueError('Cumulative paths require the explicit single_slr region policy')
    for key in ('base','weight'):
        if not isinstance(value.get(key),(int,float)) or not math.isfinite(value[key]):
            raise ValueError('Invalid cumulative path '+key)
    if value['base']<=1 or value['weight']<=0:
        raise ValueError('Cumulative path base must exceed one and weight must be positive')
    for key in ('incremental_max_nodes','assignment_cache_entries'):
        if type(value.get(key)) is not int or value[key]<1:raise ValueError('Invalid '+key)
    mode=value.get('topology_model','ff_cell_v1')
    if mode not in {'ff_cell_v1','macro_timing_v2'}:raise ValueError('Unsupported cumulative topology model')
    return dict(value,topology_model=mode)


def penalty(n,base):
    """Zero for zero/one boundaries; no silent saturation of large penalties."""
    if n<=1:return 0.
    try:value=math.expm1((n-1)*math.log(base))
    except OverflowError as error:
        raise ValueError('Exponential path cost overflow; inspect topology/base') from error
    if not math.isfinite(value):raise ValueError('Non-finite exponential path cost')
    return value


def topology(data,atom_labels,module_ids,macro_metadata=None,topology_model='macro_timing_v2'):
    """Build once from original cells, never from a quotient module graph."""
    model=PathModel(data,dict(paths=[]),{})
    owner=np.full(len(data['cells']),-1,dtype=np.int32)
    if len(atom_labels)!=len(data['atoms']):raise ValueError('Atom membership size mismatch')
    for a,cells in enumerate(data['atoms']):
        m=atom_labels[a]
        if not isinstance(m,(int,np.integer)) or not 0<=m<len(module_ids):
            raise ValueError('Unowned physical atom')
        owner[cells]=m
    if topology_model=='macro_timing_v2':
        from macro_timing import expanded
        reg,comb,launch,layers,node_cells,extra,pins=expanded(model,data,macro_metadata)
        owner=owner[node_cells]
    elif topology_model=='ff_cell_v1':
        reg,comb,launch,layers=model.reg,model.comb,model.launch,model.layers
        node_cells=np.arange(len(owner));extra={};pins={}
    else:raise ValueError('Unsupported cumulative topology model')
    relevant=reg|comb
    if np.any(owner[relevant]<0):raise ValueError('Unowned supported path node')
    if len(set(module_ids))!=len(module_ids):raise ValueError('Duplicate physical module ID')
    coverage=dict(model.coverage,observed_paths=0,topology_model=topology_model,
        criticality='Uniform original capture-cell weight 1; max over its active capture pins.',
        exceptions='Clock domains, false/multicycle paths and sensitization are not resolved by this structural cache.')
    if topology_model=='macro_timing_v2':
        coverage.update(extra)
        coverage['opaque_source_pins']={k:v for k,v in model.coverage['opaque_source_pins'].items()
                                       if not k.startswith(('DSP48','RAMB','URAM'))}
        coverage['limitations']=[
            'Conservative structural propagation, not timing sensitization or full STA.',
            'LUT/CARRY/MUX interiors retain cell-level conservative connectivity.',
            'RAM/DSP use active native pin arcs; SRL/LUTRAM/latches and other unlisted macros remain opaque.',
            'Single-SLR core regions only; soft spill, backend replicas and routed detours are not predicted.']
        coverage.update(timing_state_cells=int(reg.sum()),expanded_nodes=len(owner),
                        launch_edges=len(launch[0]),comb_edges=sum(len(a) for a,b in layers),
                        topological_layers=len(layers))
    return dict(schema=SCHEMA,topology_model=topology_model,module_ids=list(module_ids),owner=owner,
                reg=reg,comb=comb,launch=launch,layers=layers,coverage=coverage,
                node_cells=node_cells,macro_pin_nodes=pins,
                macro_binding=macro_metadata.get('binding') if macro_metadata else None)


def require_model(graph,cfg):
    if graph.get('topology_model','ff_cell_v1')!=cfg.get('topology_model','ff_cell_v1'):
        raise ValueError('Stale cumulative topology model; rebuild the path cache with native macro metadata')



def assignment(plan,module_ids):
    if set(plan)!=set(module_ids):raise ValueError('Cumulative path module IDs differ from regions')
    answer=[]
    for m in module_ids:
        slrs=plan[m]['slrs']
        if len(slrs)!=1 or type(slrs[0]) is not int or slrs[0]<0:
            raise ValueError('Cumulative path scoring requires single-SLR core regions: '+m)
        answer.append(slrs[0])
    return tuple(answer)


def independent_score(graph,plan,cfg):
    """Scalar forward relaxation for independent final verification."""
    require_model(graph,cfg)
    slrs=assignment(plan,graph['module_ids']);owner=graph['owner']
    reach=[-1]*len(owner)
    for a,b in zip(*graph['launch']):
        a,b=int(a),int(b)
        reach[b]=max(reach[b],abs(slrs[int(owner[a])]-slrs[int(owner[b])]))
    for aa,bb in graph['layers']:
        for a,b in zip(aa,bb):
            a,b=int(a),int(b)
            if reach[a]>=0:
                reach[b]=max(reach[b],reach[a]+abs(slrs[int(owner[a])]-slrs[int(owner[b])]))
    hist=Counter(reach[i] for i,reg in enumerate(graph['reg']) if reg and reach[i]>=0)
    # Deliberately use powers rather than the optimizer's expm1 curve.
    raw=sum(count*(cfg['base']**max(0,n-1)-1) for n,count in hist.items())
    return dict(cumulative_path_raw=float(raw),cumulative_path_term=float(cfg['weight']*raw),
                cumulative_path_endpoint_histogram=dict(sorted(hist.items())),
                cumulative_path_endpoints=sum(hist.values()),
                cumulative_path_over_one=sum(c for n,c in hist.items() if n>1),
                cumulative_path_max_boundaries=max(hist,default=0))


class CumulativePaths:
    def __init__(self,graph,cfg):
        if graph['schema']!=SCHEMA:raise ValueError('Stale cumulative path cache')
        require_model(graph,cfg)
        self.graph=graph;self.cfg=cfg;self.ids=graph['module_ids'];self.owner=graph['owner']
        self.reg=graph['reg'];self.n=len(self.owner);self.key=None;self.cache=OrderedDict()
        groups=[graph['launch'],*graph['layers']]
        self.a=np.concatenate([aa for aa,bb in groups]);self.b=np.concatenate([bb for aa,bb in groups])
        self.pred_indptr,self.pred=self.csr(self.b,self.a)
        comb_sources=~self.reg[self.a]
        self.next_indptr,self.next=self.csr(self.a[comb_sources],self.b[comb_sources])
        self.rank=np.zeros(self.n,dtype=np.int32)
        for i,(aa,bb) in enumerate(graph['layers'],1):self.rank[aa]=i
        self.rank[self.reg]=len(graph['layers'])+1
        self.incident={m:np.unique(self.b[(self.owner[self.a]==i)|(self.owner[self.b]==i)])
                       for i,m in enumerate(self.ids)}
        self.reach=np.full(self.n,-1,dtype=np.int32);self.hist=Counter();self.curves={}
        self.stats=Counter();self.last_update={}

    def csr(self,rows,values):
        order=np.argsort(rows,kind='stable')
        ptr=np.r_[0,np.cumsum(np.bincount(rows,minlength=self.n))]
        return ptr,values[order]

    def curve(self,n):
        if n not in self.curves:self.curves[n]=penalty(n,self.cfg['base'])
        return self.curves[n]

    def _result(self,details):
        raw=math.fsum(count*self.curve(n) for n,count in self.hist.items() if count)
        term=self.cfg['weight']*raw
        if not math.isfinite(term):raise ValueError('Exponential path cost overflow')
        result=dict(cumulative_path_raw=raw,cumulative_path_term=term,
            cumulative_path_endpoints=sum(self.hist.values()),
            cumulative_path_over_one=sum(c for n,c in self.hist.items() if n>1),
            cumulative_path_max_boundaries=max((n for n,c in self.hist.items() if c),default=0))
        if details:result['cumulative_path_endpoint_histogram']=dict(sorted((n,c) for n,c in self.hist.items() if c))
        return result

    def full(self,key):
        slr=np.asarray(key,dtype=np.int32)[np.maximum(self.owner,0)]
        reach=np.full(self.n,-1,dtype=np.int32)
        a,b=self.graph['launch'];np.maximum.at(reach,b,np.abs(slr[a]-slr[b]))
        for a,b in self.graph['layers']:
            live=reach[a]>=0
            np.maximum.at(reach,b[live],reach[a[live]]+np.abs(slr[a[live]]-slr[b[live]]))
        self.reach=reach;self.hist=Counter(map(int,reach[self.reg & (reach>=0)]));self.key=key
        self.stats['full_propagations']+=1

    def update(self,key):
        if self.key is None:
            self.full(key);self.last_update=dict(mode='full',visited=self.n);return
        changed=[m for i,m in enumerate(self.ids) if key[i]!=self.key[i]]
        if not changed:
            self.last_update=dict(mode='unchanged_slrs',visited=0);return
        pending=set(int(v) for m in changed for v in self.incident[m])
        limit=self.cfg['incremental_max_nodes']
        if len(pending)>limit:
            self.full(key);self.last_update=dict(mode='full_fallback',visited=self.n);return
        queue=[(int(self.rank[v]),v) for v in pending];heapq.heapify(queue)
        visited=0;slr=np.asarray(key,dtype=np.int32)[np.maximum(self.owner,0)]
        while queue:
            _,v=heapq.heappop(queue);pending.remove(v);visited+=1
            if visited>limit:
                self.full(key);self.last_update=dict(mode='full_fallback',visited=visited);return
            pred=self.pred[self.pred_indptr[v]:self.pred_indptr[v+1]]
            starts=np.where(self.reg[pred],0,self.reach[pred]);live=starts>=0
            value=int(np.max(starts[live]+np.abs(slr[pred[live]]-slr[v]))) if np.any(live) else -1
            old=int(self.reach[v])
            if value==old:continue
            self.reach[v]=value
            if self.reg[v]:
                if old>=0:self.hist[old]-=1
                if value>=0:self.hist[value]+=1
            for b in self.next[self.next_indptr[v]:self.next_indptr[v+1]]:
                b=int(b)
                if b not in pending:
                    pending.add(b);heapq.heappush(queue,(int(self.rank[b]),b))
        self.key=key;self.stats['incremental_propagations']+=1
        self.stats['incremental_visited_nodes']+=visited
        self.last_update=dict(mode='incremental',visited=visited)

    def components(self,plan,details=False):
        key=assignment(plan,self.ids)
        if key in self.cache:
            self.stats['assignment_cache_hits']+=1;self.last_update=dict(mode='assignment_cache',visited=0)
            saved=self.cache.pop(key);self.cache[key]=saved
            return dict(saved) if details else {k:v for k,v in saved.items() if k!='cumulative_path_endpoint_histogram'}
        self.update(key);result=self._result(True);self.cache[key]=result
        while len(self.cache)>self.cfg['assignment_cache_entries']:self.cache.popitem(last=False)
        return dict(result) if details else {k:v for k,v in result.items() if k!='cumulative_path_endpoint_histogram'}
