"""Connectivity-only coarse modules from an immutable post-opt inventory."""
import argparse
import csv
import gzip
import json
import math
import pickle
import re
import time
from collections import Counter, defaultdict
from pathlib import Path

csv.field_size_limit(100_000_000)
RESOURCES = ('LUT', 'FF', 'DSP', 'BRAM18', 'URAM', 'CARRY8', 'MUXF7', 'MUXF8', 'LUTMEM')
# Logical modules may span SLRs; only the whole device is a hard resource bound.
SLR_CAPS = dict(LUT=432000, FF=864000, DSP=3072, BRAM18=1344, URAM=320)
CAPS = {r: 4*capacity for r,capacity in SLR_CAPS.items()}


def log(message, **values):
    print(json.dumps(dict(phase=message, time=time.time(), **values)), flush=True)


def rows(path):
    with path.open() as f:
        yield from csv.DictReader(f, delimiter='\t')


def resources(ref):
    if re.fullmatch(r'LUT[1-6](_2)?', ref): return {'LUT': 1}
    if ref.startswith(('FD', 'LD')): return {'FF': 1}
    if ref.startswith('DSP'): return {'DSP': 1}
    if ref.startswith(('RAMB36', 'FIFO36')): return {'BRAM18': 2}
    if ref.startswith(('RAMB18', 'FIFO18')): return {'BRAM18': 1}
    if ref.startswith('URAM'): return {'URAM': 1}
    if ref == 'CARRY8': return {'CARRY8': 1}
    if ref in ('MUXF7', 'MUXF8'): return {ref: 1}
    if ref in ('SRL16E', 'SRLC32E'): return {'LUT': 1, 'LUTMEM': 1}
    if ref in ('GND', 'VCC') or ref.startswith(('BUFG', 'BUFH', 'BUFCE')): return {}
    raise ValueError('Unsupported primitive: ' + ref)


def infrastructure(ref):
    if ref in ('GND', 'VCC'): return 'CONSTANT'
    if ref.startswith(('BUFG', 'BUFH', 'BUFCE')): return 'CLOCK'
    return None


def pin(token):
    if token.startswith('PORT:'): return token, ''
    cell, name = token.split(':', 1)
    return int(cell[1:]), name


def control_pin(ref, name):
    name = name.split('[', 1)[0].upper()
    if ref.startswith(('FD', 'LD')):
        return name in {'CE', 'GE', 'R', 'S', 'CLR', 'PRE'}
    if ref.startswith(('RAMB', 'URAM', 'DSP', 'SRL')):
        return name.startswith(('CE', 'RST', 'RESET', 'EN', 'WE'))
    return False


def linked(a_ref, a_pin, b_ref, b_pin):
    a_pin = a_pin.split('[', 1)[0].upper()
    b_pin = b_pin.split('[', 1)[0].upper()
    if a_ref.startswith('DSP') and b_ref.startswith('DSP'):
        return (a_pin, b_pin) in {('ACOUT', 'ACIN'), ('BCOUT', 'BCIN'),
                                ('PCOUT', 'PCIN'), ('CARRYCASCOUT', 'CARRYCASCIN'),
                                ('MULTSIGNOUT', 'MULTSIGNIN')}
    if a_ref.startswith('CARRY') and b_ref.startswith('CARRY'):
        return a_pin == 'CO' and b_pin == 'CI'
    if a_ref.startswith(('RAMB', 'URAM')) and b_ref.startswith(('RAMB', 'URAM')):
        return a_pin.startswith('CAS') and 'OUT' in a_pin and b_pin.startswith('CAS') and 'IN' in b_pin
    if b_pin in ('I0', 'I1'):
        return (b_ref == 'MUXF7' and a_ref.startswith('LUT') or
                b_ref == 'MUXF8' and a_ref == 'MUXF7') and a_pin in ('O', 'O6')
    return False


class Union:
    def __init__(self, n): self.parent = list(range(n))
    def find(self, a):
        while a != self.parent[a]:
            self.parent[a] = self.parent[self.parent[a]]
            a = self.parent[a]
        return a
    def join(self, a, b):
        a, b = self.find(a), self.find(b)
        self.parent[max(a, b)] = min(a, b)


def prepare(root):
    if not (root / 'raw/connectivity_complete.txt').exists():
        raise ValueError('Native connectivity export did not complete')
    cells = list(rows(root / 'raw/cells.tsv'))
    refs = [r['primitive'] for r in cells]
    for i, row in enumerate(cells):
        assert row['cell_id'] == f'c{i}'
        resources(row['primitive'])
    union = Union(len(cells))
    nets = []
    stats = Counter()
    log('read_native_nets', cells=len(cells))
    for row in rows(root / 'raw/nets.tsv'):
        stats['nets'] += 1
        drivers = [pin(t) for t in row['drivers'].split(',') if t]
        sinks = [pin(t) for t in row['sinks'].split(',') if t]
        if row['type'] in ('GROUND', 'POWER') or any(isinstance(c, int) and refs[c] in ('GND', 'VCC') for c, _ in drivers):
            stats['constant_nets'] += 1
            continue
        if row['type'] == 'CLOCK' or any(isinstance(c, int) and infrastructure(refs[c]) == 'CLOCK' for c, _ in drivers):
            stats['clock_nets'] += 1
            continue
        if not sinks:
            stats['no_sink_nets'] += 1
            continue
        if len(drivers) != 1:
            raise ValueError(f'Nonconstant net needs exactly one driver: {row["net_id"]}, {drivers[:4]}')
        d, dp = drivers[0]
        logic_sinks = [(c, p) for c, p in sinks if isinstance(c, int)]
        weight = 1 if logic_sinks and all(control_pin(refs[c], p) for c, p in logic_sinks) else 4
        if isinstance(d, int):
            for c, p in logic_sinks:
                if linked(refs[d], dp, refs[c], p):
                    union.join(d, c)
                    stats['dedicated_links'] += 1
        nets.append((row['net_id'], d, tuple(c for c, _ in sinks), weight))
        stats['signal_nets'] += 1
        stats['signal_sink_pins'] += len(sinks)
    atoms_by_root = defaultdict(list)
    for i, ref in enumerate(refs):
        if not infrastructure(ref): atoms_by_root[union.find(i)].append(i)
    atoms = list(atoms_by_root.values())
    atom_of = [-1] * len(cells)
    for a, members in enumerate(atoms):
        for c in members: atom_of[c] = a
    atom_resources = []
    for members in atoms:
        demand = Counter()
        for c in members: demand.update(resources(refs[c]))
        assert all(demand[r] <= cap for r, cap in CAPS.items()), demand
        atom_resources.append(dict(demand))
    edges = Counter()
    active = set()
    for _, driver, sinks, weight in nets:
        vertices = {atom_of[c] for c in (driver, *sinks) if isinstance(c, int) and atom_of[c] >= 0}
        if len(vertices) > 1:
            vertices = tuple(sorted(vertices))
            edges[vertices] += weight
            active.update(vertices)
    # Isolated atoms keep explicit ownership, without floorplan eligibility.
    totals = Counter()
    for r in refs: totals.update(resources(r))
    stats.update(cells=len(cells), logic_cells=sum(len(a) for a in atoms), atoms=len(atoms),
                 hyperedges=len(edges), isolated_atoms=len(atoms)-len(active))
    data = dict(cells=cells, atoms=atoms, atom_resources=atom_resources, atom_of=atom_of,
                nets=nets, edges=list(edges.items()), active_atoms=sorted(active), stats=dict(stats), totals=dict(totals))
    with (root / 'graph.pkl').open('wb') as f: pickle.dump(data, f, protocol=5)
    (root / 'inventory.json').write_text(json.dumps(dict(stats=stats, resources=totals,
        max_atom_cells=max(map(len, atoms))), indent=2)+'\n')
    log('prepared', **stats, resources=totals)


def write_hgr(path, vertices, edges, weights):
    index = {v: i+1 for i, v in enumerate(vertices)}
    projected = Counter()
    for edge, weight in edges:
        pins = tuple(index[v] for v in edge if v in index)
        if len(pins) > 1: projected[pins] += weight
    with path.open('w') as f:
        f.write(f'{len(projected)} {len(vertices)} 11\n')
        for pins, weight in projected.items(): f.write(str(weight)+' '+' '.join(map(str,pins))+'\n')
        for v in vertices: f.write(str(weights[v])+'\n')


def run_kahypar(root, data, vertices, k, caps, weights, tag, seed):
    import kahypar
    path = root / f'{tag}.hgr'
    write_hgr(path, vertices, data['edges'], weights)
    ctx = kahypar.Context()
    ctx.loadINIconfiguration(str(root / 'source/km1.ini'))
    ctx.setK(k)
    ctx.setEpsilon(0.0)
    ctx.setCustomTargetBlockWeights(caps)
    ctx.setSeed(seed)
    ctx.suppressOutput(True)
    hg = kahypar.createHypergraphFromFile(str(path), k)
    log('partition_start', tag=tag, vertices=len(vertices), k=k, caps=caps)
    kahypar.partition(hg, ctx)
    groups = defaultdict(list)
    for i, v in enumerate(vertices): groups[hg.blockID(i)].append(v)
    assert all(hg.blockWeight(i) <= caps[i] for i in range(k))
    log('partition_complete', tag=tag, km1=kahypar.connectivityMinusOne(hg)/4,
        blocks=[hg.blockWeight(i) for i in range(k)])
    return list(groups.values())


def demand_of(data, members):
    r = Counter()
    for a in members: r.update(data['atom_resources'][a])
    return r


def fits(data, members, cell_cap):
    r = demand_of(data, members)
    return sum(len(data['atoms'][a]) for a in members) <= cell_cap and all(r[key] <= val for key,val in CAPS.items())


def partition(root, k, cell_cap, seed):
    with (root / 'graph.pkl').open('rb') as f: data = pickle.load(f)
    vertices = data['active_atoms']
    weights = [len(a) for a in data['atoms']]
    assert max(weights[a] for a in vertices) <= cell_cap and sum(weights[a] for a in vertices) < k*cell_cap
    groups = run_kahypar(root, data, vertices, k, [cell_cap]*k, weights, f'k{k}_s{seed}', seed)
    pending, final = groups, []
    split_index = 0
    while pending:
        members = pending.pop(0)
        demand = demand_of(data, members)
        bad = [r for r, cap in CAPS.items() if demand[r] > cap]
        if not bad:
            final.append(members)
            continue
        resource = max(bad, key=lambda r: demand[r]/CAPS[r])
        n = sum(weights[a] for a in members)
        scale = n+1
        custom = {a: data['atom_resources'][a].get(resource, 0)*scale+weights[a] for a in members}
        target = CAPS[resource]*scale+n
        pieces = math.ceil(demand[resource]/CAPS[resource])
        split = run_kahypar(root, data, members, pieces, [target]*pieces, custom,
                           f'k{k}_s{seed}_resource{split_index}', seed)
        assert len(split)>1
        pending.extend(split); split_index += 1
    # Merge connected blocks whenever caps permit. This removes forced k-way
    # fragments without introducing any equal-size or minimum-size preference.
    merged = []
    while True:
        owner = {a: i for i,g in enumerate(final) for a in g}
        gain = Counter()
        for edge, weight in data['edges']:
            blocks = sorted({owner[a] for a in edge})
            for pos, a in enumerate(blocks):
                for b in blocks[pos+1:]: gain[a,b] += weight
        choice = None
        for (a,b), value in sorted(gain.items(), key=lambda x:(-x[1],x[0])):
            if fits(data, final[a]+final[b], cell_cap): choice=(a,b,value); break
        if choice is None: break
        a,b,value = choice
        final[a].extend(final[b]); del final[b]
        merged.append(value/4)
    final.sort(key=lambda g:(-sum(weights[a] for a in g), min(g)))
    membership = [-1]*len(data['atoms'])
    for m, group in enumerate(final):
        assert fits(data, group, cell_cap)
        for a in group:
            assert membership[a] == -1
            membership[a]=m
    assert all(membership[a]>=0 for a in vertices)
    km1 = sum(w*(len({membership[v] for v in e})-1) for e,w in data['edges'])/4
    cut = sum(w for e,w in data['edges'] if len({membership[v] for v in e})>1)/4
    out = root / f'result_k{k}_s{seed}'
    out.mkdir()
    result=dict(k_requested=k, cell_cap=cell_cap, seed=seed, modules=len(final),
                weighted_km1=km1, weighted_cut=cut, merge_gains=merged,
                resource_splits=split_index, resource_caps=CAPS,
                groups=final, membership=membership)
    (out/'partition.json').write_text(json.dumps(result)+'\n')
    log('final_candidate', **{a:b for a,b in result.items() if a not in ('groups','membership')})


def summaries(data, result):
    labels = result['membership']
    owner = []
    for i,row in enumerate(data['cells']):
        kind = infrastructure(row['primitive'])
        label = labels[data['atom_of'][i]] if not kind else -1
        owner.append(kind if kind else ('FREE' if label<0 else f'P{label:02d}'))
    pairs = defaultdict(lambda: Counter())
    ports = defaultdict(lambda: Counter())
    internal = Counter(); boundary = Counter(); fanout = Counter()
    raw_cut=0; raw_km1=0; weighted_cut=0; weighted_km1=0
    for net_id,driver,sinks,weight in data['nets']:
        d = owner[driver] if isinstance(driver,int) else 'PORT'
        destinations = Counter(owner[s] if isinstance(s,int) else 'PORT' for s in sinks)
        blocks = {owner[c] for c in (driver,*sinks) if isinstance(c,int) and owner[c].startswith('P')}
        if len(blocks)>1:
            raw_cut+=1; raw_km1+=len(blocks)-1
            weighted_cut+=weight/4; weighted_km1+=weight/4*(len(blocks)-1)
            for m in blocks: boundary[m]+=1
        for s, count in destinations.items():
            if d=='PORT' or s=='PORT':
                if d!=s:
                    ports[d,s]['nets']+=1; ports[d,s]['sink_pin_connections']+=count
            elif d==s:
                internal[d]+=count
            else:
                pairs[d,s]['nets']+=1
                pairs[d,s]['sink_pin_connections']+=count
                pairs[d,s]['weighted_nets']+=weight/4
                pairs[d,s]['data_nets' if weight==4 else 'control_nets']+=1
        if d.startswith('P') and d!='PORT': fanout[d]=max(fanout[d],len(sinks))
    assert weighted_km1 == result['weighted_km1']
    assert weighted_cut == result['weighted_cut']
    modules = []
    for m,group in enumerate(result['groups']):
        mid=f'P{m:02d}'
        members=[c for a in group for c in data['atoms'][a]]
        original=Counter(data['cells'][c]['cell_name'].split('/')[0] if '/' in data['cells'][c]['cell_name'] else 'TOP' for c in members)
        level2=Counter('/'.join(data['cells'][c]['cell_name'].split('/')[:2]) if data['cells'][c]['cell_name'].count('/')>=2 else original_owner(data['cells'][c]) for c in members)
        demand=demand_of(data,group)
        outgoing=sum(p['sink_pin_connections'] for (a,b),p in pairs.items() if a==mid)
        incoming=sum(p['sink_pin_connections'] for (a,b),p in pairs.items() if b==mid)
        modules.append(dict(module_id=mid,cells=len(members),**{r:demand[r] for r in RESOURCES},
                            raw_capacity_min_slrs=max(1,max(math.ceil(demand[r]/cap) for r,cap in SLR_CAPS.items() if r!='LUT')),
                            top_direct_cells=original['TOP'], floorplan_eligible=bool(incoming+outgoing),
                            internal_pin_connections=internal[mid],incoming_pin_connections=incoming,
                            outgoing_pin_connections=outgoing,boundary_nets=boundary[mid],
                            max_driver_fanout=fanout[mid],original_owners=original.most_common(),
                            principal_subhierarchies=level2.most_common(8)))
    return owner,modules,pairs,ports,dict(cut_nets=raw_cut,km1=raw_km1,
            weighted_cut=weighted_cut,weighted_km1=weighted_km1)


def original_owner(row):
    return row['cell_name'].split('/')[0] if '/' in row['cell_name'] else 'TOP'


def write_table(path, rows, fields):
    with path.open('w') as f:
        writer=csv.DictWriter(f,fieldnames=fields,delimiter='\t',extrasaction='ignore')
        writer.writeheader(); writer.writerows(rows)


def normalize_multislr(data, original):
    """Rejoin resource-only fragments under the user's multi-SLR semantics."""
    result=dict(original)
    groups=[list(group) for group in original['groups']]
    gains=[]
    while True:
        owner={a:i for i,g in enumerate(groups) for a in g}
        gain=Counter()
        for edge,weight in data['edges']:
            blocks=sorted({owner[a] for a in edge})
            for i,a in enumerate(blocks):
                for b in blocks[i+1:]: gain[a,b]+=weight
        selected=None
        for (a,b),value in sorted(gain.items(),key=lambda x:(-x[1],x[0])):
            if fits(data,groups[a]+groups[b],result['cell_cap']):
                selected=a,b,value; break
        if selected is None: break
        a,b,value=selected
        groups[a].extend(groups[b]);del groups[b];gains.append(value/4)
    groups.sort(key=lambda g:(-sum(len(data['atoms'][a]) for a in g),min(g)))
    labels=[-1]*len(data['atoms'])
    for i,g in enumerate(groups):
        assert fits(data,g,result['cell_cap'])
        for a in g: labels[a]=i
    result.update(groups=groups,membership=labels,modules=len(groups),
                  resource_caps=CAPS,single_slr_caps=SLR_CAPS,multislr_merge_gains=gains,
                  weighted_km1=sum(w*(len({labels[a] for a in e})-1) for e,w in data['edges'])/4,
                  weighted_cut=sum(w for e,w in data['edges'] if len({labels[a] for a in e})>1)/4)
    return result


def deliver(root):
    with (root/'graph.pkl').open('rb') as f: data=pickle.load(f)
    candidates=[]
    for path in sorted(root.glob('result_k*_s*/partition.json')):
        r=json.loads(path.read_text()); r['path']=str(path.parent)
        candidates.append(normalize_multislr(data,r))
    result=min(candidates,key=lambda r:(r['weighted_km1'],r['weighted_cut'],r['modules']))
    owner,modules,pairs,ports,metrics=summaries(data,result)
    out=root/'final'; out.mkdir()
    with gzip.open(out/'leaf_cells.tsv.gz','wt') as f:
        fields=['cell_id','cell_name','primitive','original_hierarchy','module_id',*RESOURCES]
        writer=csv.DictWriter(f,fieldnames=fields,delimiter='\t');writer.writeheader()
        for row,mid in zip(data['cells'],owner):
            demand=resources(row['primitive'])
            writer.writerow(dict(row,module_id=mid,**{r:demand.get(r,0) for r in RESOURCES}))
    write_table(out/'module_resources.tsv',modules,['module_id','cells',*RESOURCES,'top_direct_cells','raw_capacity_min_slrs','floorplan_eligible',
                'internal_pin_connections','incoming_pin_connections','outgoing_pin_connections','boundary_nets','max_driver_fanout'])
    connection_rows=[dict(source=a,sink=b,**{key:p[key] for key in
        ('nets','sink_pin_connections','weighted_nets','data_nets','control_nets')})
        for (a,b),p in sorted(pairs.items())]
    write_table(out/'module_connections.tsv',connection_rows,['source','sink','nets','sink_pin_connections','weighted_nets','data_nets','control_nets'])
    write_table(out/'port_connections.tsv',[dict(source=a,sink=b,**p) for (a,b),p in sorted(ports.items())],
                ['source','sink','nets','sink_pin_connections'])
    hierarchy=[dict(module_id=m['module_id'],original_owner=h,cells=n) for m in modules for h,n in m['original_owners']]
    write_table(out/'module_hierarchy.tsv',hierarchy,['module_id','original_owner','cells'])
    infrastructure_counts=Counter(mid for mid in owner if not mid.startswith('P'))
    summary=dict(input_dcp='/Projects/jinyang/workspace/non_dataflow_crossSLR/case/FPGA_benchmark/runs/trtrs_postopt_extraction_20260917_01/optimized/post_opt.dcp',
        input_sha256='acddf4787ec2806da9bbe9131bfee33bf9db1019f636fbe2e605c868275eac7f',
        method='KaHyPar 1.3.7 km1; dedicated-cascade/MUX atoms; connected cap-safe block merging',
        resource_semantics='primitive demand, LUTMEM is a subset of LUT; no packing inference',
        control_weight=.25,data_weight=1,resource_caps=CAPS,single_slr_caps=SLR_CAPS,cell_cap=result['cell_cap'],
        selected_seed=result['seed'],initial_k=result['k_requested'],modules=modules,
        metrics=metrics,inventory=data['stats'],total_resources=data['totals'],
        infrastructure=dict(infrastructure_counts),connections=connection_rows,
        candidates=[{k:v for k,v in r.items() if k not in ('groups','membership')} for r in candidates])
    assert sum(m['cells'] for m in modules)+sum(infrastructure_counts.values()) == len(data['cells'])
    free_resources=Counter()
    for row,mid in zip(data['cells'],owner):
        if mid=='FREE': free_resources.update(resources(row['primitive']))
    summary['free_resources']=dict(free_resources)
    for r in RESOURCES: assert sum(m[r] for m in modules)+free_resources[r]==data['totals'].get(r,0)
    (out/'modules.json').write_text(json.dumps(summary,indent=2)+'\n')
    log('delivered', modules=len(modules),infrastructure=infrastructure_counts,**metrics)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['prepare','partition','deliver'])
    parser.add_argument('root',type=Path)
    parser.add_argument('--k',type=int,default=8)
    parser.add_argument('--cell-cap',type=int,default=150000)
    parser.add_argument('--seed',type=int,default=0)
    args=parser.parse_args()
    if args.action=='prepare': prepare(args.root)
    elif args.action=='partition': partition(args.root,args.k,args.cell_cap,args.seed)
    else: deliver(args.root)
