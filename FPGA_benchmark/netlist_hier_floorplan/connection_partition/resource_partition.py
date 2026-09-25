"""Resource-vector partitioning with no positions, distance or count penalty."""
from collections import Counter
import csv
import math

import partition as base
from improve import objective, soft_edges
from structure_frontend import label_groups

SCHEMA = 'resource_logic_v1'
RESOURCES = base.RESOURCES


def profile_from_cr_table(path, ratios):
    """Read only resource totals and die grouping; x/y are never consumed."""
    by_die, counts = {}, Counter()
    with path.open() as stream:
        for row in csv.DictReader(stream, delimiter='\t'):
            die = row['slr']
            counts[die] += 1
            sm = int(row['SLICEM'])
            slices = int(row['SLICEL']) + sm
            demand = dict(LUT=8*slices, FF=16*slices, DSP=int(row['DSP']),
                          BRAM18=2*int(row['BRAM36']), URAM=int(row['URAM']),
                          LUTMEM=8*sm, CARRY8=slices, MUXF7=4*slices, MUXF8=2*slices)
            by_die.setdefault(die, Counter()).update(demand)
    if not by_die:
        raise ValueError('Device capacity table is empty.')
    if set(ratios) != set(RESOURCES) or any(not 0 < v <= 1 for v in ratios.values()):
        raise ValueError('Every resource requires a capacity ratio in (0,1].')
    # Drop physical identities; equal capacity vectors are one resource class.
    unique = {}
    for die, capacities in by_die.items():
        key = tuple(capacities[r] for r in RESOURCES)
        unique[key] = {r: capacities[r] for r in RESOURCES}
    return dict(schema=SCHEMA, die_capacity_classes=[unique[k] for k in sorted(unique)],
                resource_ratios=ratios, clock_regions=sum(counts.values()),
                die_count=len(by_die), average_usable_cr={
                    r:sum(q[r] for q in by_die.values())*ratios[r]/sum(counts.values())
                    for r in RESOURCES},
                semantics='Anonymous die capacity vectors and mean usable CR resources; no module assignment or coordinates.')


class Budget:
    def __init__(self, profile):
        self.profile = profile
        ratios = profile['resource_ratios']
        self.caps = [{r:math.floor(c[r]*ratios[r]+1e-9) for r in RESOURCES}
                     for c in profile['die_capacity_classes']]
        self.average = profile['average_usable_cr']
        if not self.caps:
            raise ValueError('No die capacity vector supplied.')

    def fits(self, demand):
        # One common capacity vector must satisfy every resource. Combining
        # independently best DSP and RAM capacities from different dies is invalid.
        return any(all(demand.get(r,0) <= c[r] for r in RESOURCES) for c in self.caps)

    def equivalent_crs(self, demand):
        return max((demand.get(r,0)/self.average[r] if self.average[r] else
                    (math.inf if demand.get(r,0) else 0.) for r in RESOURCES),default=0.)

    def audit(self, data, groups, soft_min=1.):
        modules=[]
        for m, group in enumerate(groups):
            q=base.demand_of(data,group)
            area=self.equivalent_crs(q)
            modules.append(dict(module_id=f'P{m:02d}',resources={r:q[r] for r in RESOURCES},
                                equivalent_crs=area,below_soft_minimum=area<soft_min,
                                fits_one_die_budget=self.fits(q)))
        return dict(valid=all(m['fits_one_die_budget'] for m in modules),modules=modules,
                    soft_min_crs=soft_min,small_modules=sum(m['below_soft_minimum'] for m in modules),
                    positions_assigned=False,physical_feasibility_proven=False)


def score(metrics,cfg):
    """Only communication and logical-core loss; resource bounds are constraints."""
    return cfg['cut_weight']*metrics['weighted_km1']+cfg['logical_core_weight']*metrics['logical_core_loss']


def rank_rows(rows,cfg):
    feasible=[r for r in rows if r['resource_feasible'] and r.get('admissible',True)
              and r.get('protection_feasible',True)]
    if not feasible:
        return None
    # No module-count tie-break and no relative tolerance preferring fewer blocks.
    return min(feasible,key=lambda r:(score(r,cfg),r['weighted_km1'],
                                     r['logical_core_loss'],r['candidate']))


def recursive_groups(root,data,budget,target_crs,seed,splitter=base.run_kahypar,
                     fraction=.85,max_calls=1024):
    """Resource-weighted KaHyPar bisections produce fine starting modules.

The native solver has a scalar weight. Every proposed child is rechecked in
all resource dimensions; the scalar projection never certifies feasibility.
Indivisible validated operators may exceed this initial soft target, but not
the final one-die budget. There is no primitive-cell-count cap.
"""
    if target_crs <= 0 or not .5 <= fraction < 1:
        raise ValueError('Invalid initial granularity or split fraction.')
    vertices=list(range(len(data['atoms'])))
    for a,q in enumerate(data['atom_resources']):
        if not budget.fits(q):
            raise ValueError(f'Indivisible node {a} exceeds every single-die resource budget.')
    pending=[vertices] if vertices else []
    final=[];history=[];calls=0
    targets={r:target_crs*budget.average[r] for r in RESOURCES}
    while pending:
        group=pending.pop()
        q=base.demand_of(data,group)
        if len(group)==1 or all(q[r]<=targets[r]+1e-9 for r in RESOURCES):
            if budget.fits(q):
                final.append(group)
                continue
        if len(group)<2:
            raise ValueError('Resource-infeasible indivisible node.')
        if budget.fits(q):
            reference=targets
        else:
            def overflow(cap):
                return max(q[r]/cap[r] if cap[r] else (math.inf if q[r] else 0.) for r in RESOURCES)
            reference=min(budget.caps,key=overflow)
        resource=max(RESOURCES,key=lambda r:q[r]/reference[r] if reference[r] else
                     (math.inf if q[r] else 0.))
        # Preserve high-resolution resource importance while keeping native
        # node-weight totals well below signed 32-bit range. The +1 permits
        # zero-demand vertices and is not a cell-balance objective.
        scale=max(1,min(1024,(2**29)//max(1,q[resource]+len(group))))
        weights={a:1+scale*data['atom_resources'][a].get(resource,0) for a in group}
        total=sum(weights.values())
        upper=max(max(weights.values()),math.ceil(fraction*total))
        upper=min(upper,total-1)
        calls+=1
        if calls>max_calls:
            raise ValueError('Resource split call budget exhausted; no infeasible candidate emitted.')
        children=splitter(root,data,group,2,[upper,upper],weights,
                          f'resource_s{seed}_a{target_crs:g}_{calls}',seed)
        if len(children)!=2 or any(not child or len(child)>=len(group) for child in children):
            raise ValueError('Resource split did not make progress.')
        flat=[a for child in children for a in child]
        if sorted(flat)!=sorted(group):
            raise ValueError('Resource split changed membership.')
        history.append(dict(resource=resource,seed=seed,vertices=len(group),
                            scalar_scale=scale,scalar_cap=upper,children=[len(c) for c in children]))
        pending.extend(children)
    final.sort(key=lambda g:min(g))
    assert budget.audit(data,final)['valid']
    return final,dict(initial_target_crs=target_crs,split_calls=calls,history=history,
                     native_solver='KaHyPar scalar proposals; recursive exact vector screening',
                     cell_cap=None,fixed_k=None)


def affinity_statistics(data,groups):
    labels=label_groups(groups,len(data['atoms']))
    volume=Counter();shared=Counter()
    for edge,weight in data['edges']:
        touched=sorted({labels[a] for a in edge})
        for a in touched:volume[a]+=weight
        for i,a in enumerate(touched):
            for b in touched[i+1:]:shared[a,b]+=weight
    return volume,shared


def selective_merge(data,groups,budget,threshold=.02,soft_min=1.,only_small=False):
    """Use the existing relative-affinity gate; small modules get priority only."""
    groups=[list(g) for g in groups];history=[]
    while True:
        demands=[base.demand_of(data,g) for g in groups]
        small=[budget.equivalent_crs(q)<soft_min for q in demands]
        volume,shared=affinity_statistics(data,groups)
        eligible=[]
        for (a,b),gain in shared.items():
            if only_small and not (small[a] or small[b]):continue
            affinity=gain/min(volume[a],volume[b])
            if affinity<threshold or not budget.fits(demands[a]+demands[b]):continue
            eligible.append((not(small[a] or small[b]),-affinity,-gain,a,b))
        if not eligible:break
        _,affinity,gain,a,b=min(eligible)
        history.append(dict(pair=[a,b],affinity=-affinity,real_km1_gain=-gain/4,
                            small_module_priority=small[a] or small[b]))
        groups[a].extend(groups[b]);del groups[b]
    groups.sort(key=lambda g:min(g))
    audit=budget.audit(data,groups,soft_min)
    volume,shared=affinity_statistics(data,groups)
    exceptions=[]
    for m,row in enumerate(audit['modules']):
        if not row['below_soft_minimum']:continue
        adjacent=[(b if a==m else a,gain/min(volume[a],volume[b]))
                  for (a,b),gain in shared.items() if m in (a,b)]
        q=base.demand_of(data,groups[m])
        strong=[b for b,affinity in adjacent if affinity>=threshold]
        reason='no_connected_neighbor' if not adjacent else 'weak_coupling' if not strong else 'resource_budget'
        assert not any(budget.fits(q+base.demand_of(data,groups[b])) for b in strong)
        exceptions.append(dict(module_id=row['module_id'],equivalent_crs=row['equivalent_crs'],
                               reason=reason,maximum_affinity=max((a for _,a in adjacent),default=0.)))
    return groups,dict(threshold=threshold,soft_min_crs=soft_min,history=history,
                       small_module_exceptions=exceptions,resource_audit=audit)


def projected_core_edges(cores,mapping,cfg):
    """Guide KaHyPar using soft logical cores while scoring the original graph."""
    if cfg['cut_weight']<=0 or cfg['logical_core_weight']<0:
        raise ValueError('Resource partition requires positive communication weight and nonnegative core weight.')
    owner={a:i for i,group in enumerate(mapping) for a in group}
    projected=Counter()
    for pins,w in soft_edges(cores,cfg['core_soft_strength']):
        pp=tuple(sorted({owner[a] for a in pins}))
        if len(pp)>1 and cfg['logical_core_weight']:
            projected[pp]+=max(1,round(w*cfg['logical_core_weight']/cfg['cut_weight']))
    return list(projected.items())
