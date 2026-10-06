"""Register-bounded structural paths plus validated routed timing observations.

No internal RAM/DSP timing arcs are invented. FDRE/FDSE synchronous endpoints
and combinational LUT/CARRY/MUX arcs are a conservative cell-level graph.
"""
from collections import Counter, defaultdict
import re

import numpy as np

COMB = re.compile(r'(?:LUT[1-6](?:_2)?|CARRY8|MUXF[78])$')
REG = frozenset(('FDRE', 'FDSE'))


def parse_timing(text):
    """Read data-path primitive pins, never clock-network or net-name rows."""
    result = []
    for rank, block in enumerate(re.split(r'(?=^Slack \()', text, flags=re.M)[1:], 1):
        start = re.search(r'^  Source:\s+(\S+)', block, re.M).group(1)
        end = re.search(r'^  Destination:\s+(\S+)', block, re.M).group(1)
        slack = float(re.search(r'^Slack.*?:\s+([-\d.]+)ns', block).group(1))
        requirement = float(re.search(r'^  Requirement:\s+([\d.]+)ns', block, re.M).group(1))
        # The first propagation arc starts the data path after the launch clock.
        lines = block.splitlines(); active = False; pending = False; pins = []
        for line in lines:
            if re.search(r'\(Prop_', line):
                active = True; pending = True
            if not active:
                continue
            if line.strip().endswith(end):
                pins.append(end); break
            if pending:
                token = line.strip().split()[-1] if line.strip() else ''
                if '/' in token and re.search(r'/[A-Z][A-Z0-9_]*(?:\[\d+\])?$', token):
                    pins.append(token); pending = False
        cells = []
        for pin in pins:
            cell = pin.rsplit('/', 1)[0]
            if not cells or cell != cells[-1]:
                cells.append(cell)
        if not cells or cells[0] != start.rsplit('/',1)[0] or cells[-1] != end.rsplit('/',1)[0]:
            raise ValueError(f'Incomplete timing data path at rank {rank}')
        result.append(dict(rank=rank, source=start, sink=end, slack_ns=slack,
                           requirement_ns=requirement, cells=cells))
    if not result:
        raise ValueError('No setup paths found')
    return result


def bind_paths(data, reports, cfg):
    """Exact names and original directed edges are mandatory after projection."""
    names = {c['cell_name']: i for i,c in enumerate(data['cells'])}
    projected = []; excluded = []; needed = set()
    for path in reports:
        ids = []; helpers = []; unknown = []
        for name in path['cells']:
            if name in names:
                ids.append(names[name])
            elif re.fullmatch(r'f96_identity_\d+', name):
                helpers.append(name)
            else:
                unknown.append(name)
        if unknown or not ids or path['cells'][0] not in names or path['cells'][-1] not in names:
            excluded.append(dict(rank=path['rank'], reason='unmapped_original_cell', cells=unknown)); continue
        if any(data['cells'][c]['primitive'].startswith(('FD','LD')) for c in ids[1:-1]):
            excluded.append(dict(rank=path['rank'], reason='interior_state_boundary')); continue
        if len(set(ids)) != len(ids):
            excluded.append(dict(rank=path['rank'], reason='repeated_cell_arc_not_modeled')); continue
        pairs = list(zip(ids,ids[1:])); needed.update(pairs)
        projected.append(dict(path, cell_ids=ids, projected_helpers=helpers, pairs=pairs))
    found = set()
    for _,a,sinks,_ in data['nets']:
        if not isinstance(a,int): continue
        for b in sinks:
            if isinstance(b,int) and (a,b) in needed:
                found.add((a,b))
    accepted = {}; supported = []
    for path in projected:
        missing = [p for p in path.pop('pairs') if p not in found]
        if missing:
            excluded.append(dict(rank=path['rank'],reason='no_original_directed_edge',pairs=missing)); continue
        if path['requirement_ns'] <= 0:
            excluded.append(dict(rank=path['rank'],reason='nonpositive_requirement')); continue
        key=tuple(path['cell_ids'])
        fraction=max(0.,min(1.,1.-path['slack_ns']/cfg['criticality_window_ns']))
        path['criticality']=cfg['criticality_floor']+(cfg['criticality_ceiling']-cfg['criticality_floor'])*fraction
        supported.append(path['rank'])
        if key not in accepted or path['slack_ns'] < accepted[key]['slack_ns']:
            accepted[key]=path
    return dict(paths=list(accepted.values()), excluded=excluded,
                coverage=dict(reported=len(reports), accepted_reports=len(supported),
                              unique_paths=len(accepted), excluded=len(excluded)),
                semantics='Exact original names and edge validation; only known identity LUTs projected out. No guessed replica aliases.')


class PathModel:
    """Maximum accumulated SLR boundary count per capture endpoint.

    Paths stop at every register. One endpoint contributes once, even when
    several reported paths or structural branches reach it. All candidates
    require single-SLR physical regions, preserving coherent cell locations.
    """
    def __init__(self, data, feedback, cfg):
        self.data=data; self.feedback=feedback; self.cfg=cfg
        refs=[c['primitive'] for c in data['cells']]
        self.comb=np.array([bool(COMB.fullmatch(r)) for r in refs])
        self.reg=np.array([r in REG for r in refs])
        self.n=len(refs); incoming=np.zeros(self.n,dtype=np.int32)
        comb_edges=set(); launch_edges=set(); unsupported=Counter()
        for _,a,sinks,_ in data['nets']:
            if not isinstance(a,int): continue
            for b in sinks:
                if not isinstance(b,int): continue
                if self.comb[b] or self.reg[b]:
                    if self.reg[a]: launch_edges.add((a,b))
                    elif self.comb[a]: comb_edges.add((a,b))
                    else: unsupported[refs[a]]+=1
        self.launch=self.arrays(sorted(launch_edges))
        adjacency=defaultdict(list)
        for a,b in comb_edges:
            adjacency[a].append(b)
            if self.comb[b]: incoming[b]+=1
        queue=np.flatnonzero(self.comb & (incoming==0)).tolist(); layers=[]; visited=0
        while queue:
            visited+=len(queue); pairs=[]; following=[]
            for a in queue:
                for b in adjacency.get(a,()):
                    pairs.append((a,b))
                    if self.comb[b]:
                        incoming[b]-=1
                        if incoming[b]==0: following.append(b)
            if pairs: layers.append(self.arrays(pairs))
            queue=following
        if visited != int(self.comb.sum()):
            raise ValueError('Combinational cycle in supported structural graph')
        self.layers=layers
        self.observed=[(np.array(p['cell_ids'],dtype=np.int32),p) for p in feedback['paths']]
        self.weights=np.ones(self.n)
        for ids,p in self.observed:
            self.weights[ids[-1]]=max(self.weights[ids[-1]],p['criticality'])
        self.coverage=dict(registers=int(self.reg.sum()),comb_cells=int(self.comb.sum()),
            launch_edges=len(launch_edges),comb_edges=len(comb_edges),topological_layers=len(layers),
            opaque_source_pins=dict(unsupported),observed_paths=len(self.observed),
            limitations=['Conservative cell-level FF-to-FF connectivity, not timing sensitization or full STA.',
                        'Only FDRE/FDSE and LUT/CARRY8/MUXF7/MUXF8 interiors modeled structurally.',
                        'RAM/DSP, LUTRAM, latches and other macros require validated observed paths.',
                        'Single-SLR core candidates only; soft spill and routed detours are not predicted.'])

    @staticmethod
    def arrays(pairs):
        if not pairs: return np.array([],dtype=np.int32),np.array([],dtype=np.int32)
        arr=np.array(pairs,dtype=np.int32); return arr[:,0],arr[:,1]

    def slrs(self, owners, regions):
        slrs={m:r['slrs'][0] for m,r in regions.items() if len(r['slrs'])==1}
        if len(slrs)!=len(regions): raise ValueError('Path refinement requires single-SLR core regions')
        return np.array([slrs.get(m,-1) for m in owners],dtype=np.int32)

    def evaluate(self, owners, regions, details=False):
        slr=self.slrs(owners,regions)
        relevant=self.comb|self.reg
        if np.any(slr[relevant]<0): raise ValueError('Missing ownership of a supported timing node')
        reach=np.full(self.n,-1000000,dtype=np.int32)
        a,b=self.launch
        np.maximum.at(reach,b,np.abs(slr[a]-slr[b]))
        for a,b in self.layers:
            np.maximum.at(reach,b,reach[a]+np.abs(slr[a]-slr[b]))
        structural=np.where(self.reg & (reach>=0),reach,-1)
        endpoint=structural.copy(); observations=[]
        for ids,path in self.observed:
            n=int(np.abs(np.diff(slr[ids])).sum())
            endpoint[ids[-1]]=max(endpoint[ids[-1]],n)
            if details:
                seq=[int(slr[ids[0]])]
                for s in slr[ids[1:]]:
                    if s!=seq[-1]:seq.append(int(s))
                observations.append(dict(rank=path['rank'],slack_ns=path['slack_ns'],
                    source=path['source'],sink=path['sink'],boundaries=n,
                    extra_boundaries=n-abs(seq[-1]-seq[0]),slr_sequence=seq))
        raw=float(np.sum(self.weights*np.maximum(0,endpoint-1).astype(float)**2))
        result=dict(weighted_path_square=raw,path_square_term=self.cfg['path_square_weight']*raw,
                    supported_endpoint_count=int((endpoint>=0).sum()),
                    endpoints_over_one=int((endpoint>1).sum()),maximum_boundaries=int(endpoint.max()),
                    structural_endpoint_histogram=dict(Counter(map(int,structural[structural>=0]))),
                    endpoint_histogram=dict(Counter(map(int,endpoint[endpoint>=0]))))
        if details: result['observed_paths']=observations
        return result
