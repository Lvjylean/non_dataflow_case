"""Joint static resource regions with all-net span rescoring and local search."""
import argparse
import json
import pickle
import random
from collections import Counter
from pathlib import Path

import numpy as np

from balanced_physical import balanced_score, admissible
from physical_model import build as build_physical_model
from improve import labels_for
from static_regions import RESOURCES, LIMITS, load_device, all_rectangles, fits, overlap_audit


def options_for(module, regions, cfg):
    valid=[r for r in regions if fits(module,r)]
    if not valid:
        return [],dict(feasible_rectangles=0)
    minimum=min(r['area'] for r in valid)
    kept=[r for r in valid if r['area'] <= minimum*cfg['region_max_area_factor']+cfg['region_max_area_extra_crs']]
    return kept,dict(feasible_rectangles=len(valid),retained_rectangles=len(kept),
                     minimum_crs=minimum,minimum_slrs=min(len(r['slrs']) for r in valid),
                     search_window='All SLR spans; area <= factor*minimum area + extra CRs')


def initialize(modules, connections, options, model_net, device, cfg):
    import gurobipy as gp
    from gurobipy import GRB
    solver=gp.Model('balanced_region_initializer')
    solver.Params.OutputFlag=0;solver.Params.Threads=2;solver.Params.Seed=0
    solver.Params.TimeLimit=cfg['region_solver_seconds'];solver.Params.MIPGap=.03
    z={m:solver.addVars(len(rs),vtype=GRB.BINARY) for m,rs in options.items()}
    for m in z:solver.addConstr(z[m].sum()==1)
    for c,d in device.items():
        for resource in RESOURCES:
            if not d['resources'][resource]:continue
            terms=[]
            for m in modules:
                if not m[resource]:continue
                mid=m['module_id']
                terms.extend(z[mid][j]*m[resource]/r['capacity'][resource]
                             for j,r in enumerate(options[mid]) if c in r['crs'])
            if terms:solver.addConstr(gp.quicksum(terms)<=LIMITS[resource])
    unary={}
    for i,m in enumerate(modules):
        mid=m['module_id']
        unary[mid]=[model_net.internal_region_cost(i,r,cfg['slr_distance_weight']) for r in options[mid]]
    points={mid:[gp.quicksum(z[mid][j]*(r['center'][axis] if axis<2 else r['slr_center'])
                         for j,r in enumerate(rs)) for axis in range(3)] for mid,rs in options.items()}
    pairs=Counter()
    for edge in connections:
        pairs[tuple(sorted((edge['source'],edge['sink'])))]+=edge['weighted_nets']
    terms=[]
    for (a,b),w in pairs.items():
        for axis,factor in enumerate((1,1,cfg['slr_distance_weight'])):
            d=solver.addVar(lb=0)
            solver.addConstr(d>=points[a][axis]-points[b][axis])
            solver.addConstr(d>=points[b][axis]-points[a][axis])
            terms.append(w*factor*d)
    solver.setObjective(gp.quicksum(z[m][j]*v for m,vs in unary.items() for j,v in enumerate(vs))
                        +gp.quicksum(terms),GRB.MINIMIZE)
    solver.optimize()
    if not solver.SolCount:
        return None,dict(status='no_solution_in_search',status_code=solver.Status),unary
    chosen={m:rs[max(range(len(rs)),key=lambda j:z[m][j].X)] for m,rs in options.items()}
    return chosen,dict(status='feasible',initial_mip_objective=solver.ObjVal,
                       initial_mip_bound=solver.ObjBound,initial_mip_gap=solver.MIPGap,
                       initial_mip_seconds=solver.Runtime,status_code=solver.Status),unary


def polish(chosen, modules, options, netmodel, device, cfg, unary, seed=0):
    keys=list(device);index={c:i for i,c in enumerate(keys)}
    mask=np.array([[device[c]['resources'][r]>0 for r in RESOURCES] for c in keys])
    cache={}
    def occupancy(m,r):
        key=(m['module_id'],tuple(r['bounds']))
        if key not in cache:
            arr=np.zeros((len(keys),len(RESOURCES)))
            ratio=np.array([m[t]/r['capacity'][t] if r['capacity'][t] else 0 for t in RESOURCES])
            ids=[index[c] for c in r['crs']]
            arr[ids]=mask[ids]*ratio
            cache[key]=arr
        return cache[key]
    density=sum(occupancy(m,chosen[m['module_id']]) for m in modules)
    limits=np.array([LIMITS[r] for r in RESOURCES])
    components=netmodel.components(chosen,cfg['slr_distance_weight'])
    current=components['physical_cost'];history=[]
    rng=random.Random(seed)
    for iteration in range(cfg['region_local_search_rounds']):
        order=list(modules);rng.shuffle(order);moved=0
        for m in order:
            mid=m['module_id'];old=chosen[mid]
            pool=list(range(len(options[mid])))
            fixed=sorted(pool,key=lambda j:unary[mid][j])[:8]
            pool=rng.sample(pool,min(len(pool),cfg['region_local_search_options_per_module']))
            pool=sorted(set(pool+fixed))
            base_density=density-occupancy(m,old)
            best=None;best_cost=current
            for j in pool:
                region=options[mid][j]
                trial_density=base_density+occupancy(m,region)
                if np.any(trial_density>limits+1e-8):continue
                chosen[mid]=region
                comp=netmodel.components(chosen,cfg['slr_distance_weight'])
                if comp['physical_cost']<best_cost-1e-7:
                    best=(region,trial_density,comp);best_cost=comp['physical_cost']
            if best:
                chosen[mid],density,components=best
                current=best_cost;moved+=1
            else:chosen[mid]=old
        history.append(dict(iteration=iteration,moved_regions=moved,physical_cost=current))
        if not moved:break
    return chosen,components,history


def local_fractions(data, baseline_labels, labels):
    volume=Counter();cuts=Counter()
    for edge,w in data['edges']:
        touched={}
        for a in edge:
            touched.setdefault(baseline_labels[a],set()).add(labels[a])
        for p,groups in touched.items():
            volume[p]+=w;cuts[p]+=w*(len(groups)-1)
    return {f'P{p:02d}':dict(incident_weight=volume[p]/4,local_km1=cuts[p]/4,
                                  fraction=cuts[p]/volume[p]) for p in sorted(volume)}


def evaluate(run, names):
    cfg=json.loads((run/'source/balanced_config.json').read_text())
    if cfg.get('partition_objective') == 'resource_logic_v1':
        raise ValueError('Resource-only partition cannot evaluate physical regions; use structure_pipeline.py. Regions start in its floorplan stage.')
    with (run/'graph.pkl').open('rb') as f:data=pickle.load(f)
    binding=json.loads((run/'binding.json').read_text())
    basegroups=json.loads((run/'candidates/baseline5/groups.json').read_text())
    baselabels=labels_for(data,basegroups)
    device=load_device(run/'cr.tsv');rectangles=all_rectangles(device)
    for name in names:
        folder=run/'candidates'/name
        if (folder/'balanced_regions.json').exists():
            previous=json.loads((folder/'balanced_regions.json').read_text())
            if cfg.get('hypernet_model','all_atom_v1')=='boundary_spatial_v1' and previous.get('physical_model')!='boundary_spatial_v1':
                raise ValueError('Existing region result uses legacy D; use a new experiment directory.')
            continue
        summary=json.loads((folder/'summary.json').read_text())
        groups=json.loads((folder/'groups.json').read_text());labels=labels_for(data,groups)
        fractions=local_fractions(data,baselabels,labels)
        metrics=summary['metrics']
        metrics['maximum_local_split_fraction']=max(v['fraction'] for v in fractions.values())
        summary['local_connection_constraints']=fractions
        (folder/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
        if not admissible(metrics,cfg,2):
            (folder/'screening.json').write_text(json.dumps(dict(status='outside_even_wide_budget',metrics=metrics),indent=2)+'\n')
            print(json.dumps(dict(name=name,status='screened',**metrics)),flush=True);continue
        netmodel=build_physical_model(data,labels,len(groups),device,cfg)
        options={};stats={}
        for m in summary['modules']:
            options[m['module_id']],stats[m['module_id']]=options_for(m,rectangles,cfg)
        if any(not v for v in options.values()):
            result=dict(status='no_individual_region',candidate_stats=stats)
        else:
            chosen,initial,unary=initialize(summary['modules'],summary['connections'],options,netmodel,device,cfg)
            result=dict(initial,candidate_stats=stats)
            if chosen:
                initial_components=netmodel.components(chosen,cfg['slr_distance_weight'])
                chosen,components,history=polish(chosen,summary['modules'],options,netmodel,device,cfg,unary)
                audit=overlap_audit(summary['modules'],chosen,device);assert audit['valid']
                result.update(regions=chosen,overlap=audit,components=components,
                    initial_components=initial_components,local_search=history,
                    objective=balanced_score(components,metrics,binding['all_net_weight'],cfg),
                    total_module_crs=sum(r['area'] for r in chosen.values()),
                    maximum_slrs_per_unit=max(len(r['slrs']) for r in chosen.values()),
                    eligible_main=admissible(metrics,cfg),limits=LIMITS,
                    physical_model=cfg.get('hypernet_model','all_atom_v1'),
                    hypernet_audit=getattr(netmodel,'audit',{}),
                    pattern_count=len(netmodel.patterns),all_net_weight=binding['all_net_weight'],
                    modeled_hypernet_weight=float(netmodel.weights.sum()),
                    family_constraints={},logical_parent_overlaps=[],
                    limitations=['Static distributions are not placement or routing.',
                     'Atom locations are independent; dedicated-atom internal geometry is not expanded.',
                     'Hypernet inclusion follows physical_model and hypernet_audit; external port locations are unknown.',
                     'Region search is bounded; initial MIP gap is not a global gap for final full-net score.'])
        (folder/'balanced_regions.json').write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(dict(name=name,**{k:v for k,v in result.items() if k in
             ('status','objective','eligible_main','components','total_module_crs','maximum_slrs_per_unit','pattern_count')})),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('run',type=Path);p.add_argument('names',nargs='+')
    a=p.parse_args();evaluate(a.run,a.names)
