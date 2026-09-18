"""Static heterogeneous CR feasibility; no Vivado or timing feedback required."""
import argparse
import csv
import itertools
import json
from collections import Counter
from pathlib import Path

RESOURCES = ('LUT','FF','DSP','BRAM18','URAM','LUTMEM','CARRY8','MUXF7','MUXF8')
LIMITS = {r:(1.0 if r=='URAM' else .7) for r in RESOURCES}


def load_device(path):
    device = {}
    with Path(path).open() as f:
        for row in csv.DictReader(f,delimiter='\t'):
            sl,sm=int(row['SLICEL']),int(row['SLICEM']);slices=sl+sm
            device[row['cr']]=dict(x=int(row['x']),y=int(row['y']),slr=int(row['slr'][3:]),
                resources=dict(LUT=8*slices,FF=16*slices,DSP=int(row['DSP']),
                BRAM18=2*int(row['BRAM36']),URAM=int(row['URAM']),LUTMEM=8*sm,
                CARRY8=slices,MUXF7=4*slices,MUXF8=2*slices))
    return device


def all_rectangles(device):
    xy={(d['x'],d['y']):c for c,d in device.items()}
    xs=sorted({p[0] for p in xy});ys=sorted({p[1] for p in xy})
    regions=[]
    for x0,x1 in itertools.combinations_with_replacement(xs,2):
        for y0,y1 in itertools.combinations_with_replacement(ys,2):
            coords=list(itertools.product(range(x0,x1+1),range(y0,y1+1)))
            if any(p not in xy for p in coords): continue
            crs=[xy[p] for p in coords]
            capacity={r:sum(device[c]['resources'][r] for c in crs) for r in RESOURCES}
            slrs=sorted({device[c]['slr'] for c in crs})
            regions.append(dict(crs=crs,bounds=[x0,y0,x1,y1],capacity=capacity,
                                slrs=slrs,area=len(crs),center=[(x0+x1)/2,(y0+y1)/2],
                                slr_center=sum(device[c]['slr'] for c in crs)/len(crs)))
    return regions


def fits(demand,region,limits=LIMITS):
    return all(demand.get(r,0)<=region['capacity'][r]*limits[r]+1e-8 for r in RESOURCES)


def candidates(demand,regions):
    feasible=[r for r in regions if fits(demand,r)]
    if not feasible: return [],dict(feasible_rectangles=0)
    min_slrs=min(len(r['slrs']) for r in feasible)
    single_span=[r for r in feasible if len(r['slrs'])==min_slrs]
    min_area=min(r['area'] for r in single_span)
    # Keep all placements in the declared footprint window, not just one corner.
    retained=[r for r in single_span if r['area']<=min_area*1.5+4]
    retained.sort(key=lambda r:(r['area'],r['bounds']))
    return retained,dict(feasible_rectangles=len(feasible),min_slrs=min_slrs,
        min_crs_at_min_slrs=min_area,retained_rectangles=len(retained),
        search_window='minimum feasible SLR count, area <= 1.5*minimum + 4')


def overlap_audit(modules,chosen,device,limits=LIMITS):
    occupancy={c:Counter() for c in device}
    contributors={c:set() for c in device}
    for module in modules:
        mid=module['module_id'];region=chosen[mid]
        assert fits(module,region,limits)
        for c in region['crs']:
            contributors[c].add(mid)
            for r in RESOURCES:
                if module.get(r,0) and device[c]['resources'][r]:
                    occupancy[c][r]+=module[r]/region['capacity'][r]
    violations=[dict(cr=c,resource=r,utilization=u,limit=limits[r])
                for c,v in occupancy.items() for r,u in v.items() if u>limits[r]+1e-6]
    return dict(valid=not violations,violations=violations,
        occupied_crs=sum(bool(m) for m in contributors.values()),
        overlapping_crs=sum(len(m)>1 for m in contributors.values()),
        maximum_utilization={r:max((v[r] for v in occupancy.values()),default=0) for r in RESOURCES},
        contributions=[dict(cr=c,modules=sorted(contributors[c]),utilization=dict(v))
                       for c,v in occupancy.items() if contributors[c]])


def family_windows(modules,device):
    """Keep descendants of a baseline parent inside one contiguous SLR window."""
    families={}
    for module in modules:
        parents=module.get('baseline_parent_cells',{})
        if not parents: continue
        parent=max(parents,key=parents.get)
        if parents[parent]>.5*module['cells']:
            families.setdefault(parent,[]).append(module)
    slrs=sorted({d['slr'] for d in device.values()})
    output={}
    for parent,members in families.items():
        if len(members)<2: continue
        demand={r:sum(m.get(r,0) for m in members) for r in RESOURCES}
        windows=[]
        for length in range(1,len(slrs)+1):
            for start in range(len(slrs)-length+1):
                window=slrs[start:start+length]
                if window[-1]-window[0]+1!=length: continue
                capacity={r:sum(d['resources'][r] for d in device.values() if d['slr'] in window)
                          for r in RESOURCES}
                if fits(demand,dict(capacity=capacity)):
                    windows.append(window)
            if windows: break
        output[parent]=dict(members=[m['module_id'] for m in members],windows=windows)
    return output


def solve(summary,device,regions,time_limit=60,couple_families=False):
    import gurobipy as gp
    from gurobipy import GRB
    modules=summary['modules']
    options={};stats={}
    for module in modules:
        mid=module['module_id'];options[mid],stats[mid]=candidates(module,regions)
        if not options[mid]:
            return dict(status='no_individual_region',module=mid,candidate_stats=stats)
    model=gp.Model('static_resource_overlap');model.Params.OutputFlag=0
    model.Params.Threads=2;model.Params.Seed=0;model.Params.TimeLimit=time_limit
    model.Params.MIPGap=.03
    choose={m:model.addVars(len(opts),vtype=GRB.BINARY,name='choose_'+m) for m,opts in options.items()}
    for m in options:
        model.addConstr(choose[m].sum()==1)
    families=family_windows(modules,device) if couple_families else {}
    for parent,family in families.items():
        if not family['windows']:
            return dict(status='no_family_window',parent=parent)
        window_choice=model.addVars(len(family['windows']),vtype=GRB.BINARY,name='family_'+parent)
        model.addConstr(window_choice.sum()==1)
        for mid in family['members']:
            for j,region in enumerate(options[mid]):
                compatible=[i for i,w in enumerate(family['windows']) if set(region['slrs'])<=set(w)]
                model.addConstr(choose[mid][j]<=gp.quicksum(window_choice[i] for i in compatible))
    for c,d in device.items():
        for resource in RESOURCES:
            if not d['resources'][resource]: continue
            terms=[]
            for module in modules:
                if not module.get(resource,0): continue
                mid=module['module_id']
                terms.extend(choose[mid][j]*module[resource]/region['capacity'][resource]
                             for j,region in enumerate(options[mid]) if c in region['crs'])
            if terms: model.addConstr(gp.quicksum(terms)<=LIMITS[resource])
    points={}
    for m,opts in options.items():
        points[m]=[gp.quicksum(choose[m][j]*(r['center'][dim] if dim<2 else r['slr_center'])
                    for j,r in enumerate(opts)) for dim in range(3)]
    pair_weights=Counter()
    for edge in summary['connections']:
        pair=tuple(sorted((edge['source'],edge['sink'])))
        pair_weights[pair]+=edge.get('weighted_nets',edge['nets'])
    distances=[]
    for (a,b),weight in sorted(pair_weights.items()):
        for dim,factor in enumerate((1,1,4)):
            distance=model.addVar(lb=0)
            model.addConstr(distance>=points[a][dim]-points[b][dim])
            model.addConstr(distance>=points[b][dim]-points[a][dim])
            distances.append(weight*factor*distance)
    footprint=gp.quicksum(choose[m][j]*(r['area']+8*(len(r['slrs'])-1))
                         for m,opts in options.items() for j,r in enumerate(opts))
    # A fixed normalization permits comparison of this proxy across candidates.
    model.setObjective(footprint+gp.quicksum(distances)/10000,GRB.MINIMIZE)
    model.optimize()
    result=dict(status_code=model.Status,candidate_stats=stats,limits=LIMITS,family_constraints=families,
        runtime_seconds=model.Runtime,static_model='capacity-proportional per-resource occupancy',
        limitations=['Primitive counts do not model LUT packing or exact sites.',
            'The candidate-window search is restricted; no solution is not a device infeasibility proof.',
            'Centroid pair distances are neither actual routed wirelength nor SLL/timing.'])
    if not model.SolCount:
        result['status']='no_solution_in_search';return result
    chosen={m:opts[max(range(len(opts)),key=lambda j:choose[m][j].X)] for m,opts in options.items()}
    for family in families.values():
        used={slr for m in family['members'] for slr in chosen[m]['slrs']}
        assert any(used<=set(w) for w in family['windows'])
        family['used_slrs']=sorted(used)
    audit=overlap_audit(modules,chosen,device)
    assert audit['valid'],audit['violations']
    distance=0
    for (a,b),weight in pair_weights.items():
        aa,bb=chosen[a],chosen[b]
        distance+=weight*(sum(abs(aa['center'][d]-bb['center'][d]) for d in range(2))
                         +4*abs(aa['slr_center']-bb['slr_center']))
    multi=sum(len(r['slrs'])>1 for r in chosen.values())
    result.update(status='feasible',objective=model.ObjVal,gap=model.MIPGap,
        regions=chosen,overlap=audit,total_module_crs=sum(r['area'] for r in chosen.values()),
        multi_slr_units=multi,maximum_slrs_per_unit=max(len(r['slrs']) for r in chosen.values()),
        weighted_centroid_distance=distance,logical_parent_overlaps=[])
    heavy=[m['module_id'] for m in modules if m['URAM']]
    light=[m['module_id'] for m in modules if not m['URAM'] and m['LUT']]
    for a in heavy:
        for b in light:
            common=set(chosen[a]['crs']) & set(chosen[b]['crs'])
            if common:
                result['logical_parent_overlaps'].append(dict(resource_heavy=a,lut_dense=b,
                    shared_crs=len(common),contains_lut_region=set(chosen[b]['crs'])<=set(chosen[a]['crs'])))
    return result


def main(run,cr_file,names,time_limit,couple_families=False,output_name='static_regions.json'):
    device=load_device(cr_file);regions=all_rectangles(device)
    for name in names:
        folder=run/'candidates'/name
        out=folder/output_name
        if out.exists(): raise ValueError('Refusing to overwrite static result: '+str(out))
        summary=json.loads((folder/'summary.json').read_text())
        result=solve(summary,device,regions,time_limit,couple_families)
        out.write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(dict(candidate=name,**{k:v for k,v in result.items() if k in (
            'status','objective','gap','multi_slr_units','maximum_slrs_per_unit','total_module_crs',
            'weighted_centroid_distance','runtime_seconds')})),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('run',type=Path)
    parser.add_argument('cr_file',type=Path);parser.add_argument('names',nargs='+')
    parser.add_argument('--time-limit',type=float,default=60)
    parser.add_argument('--couple-families',action='store_true')
    parser.add_argument('--output-name',default='static_regions.json')
    args=parser.parse_args();main(args.run,args.cr_file,args.names,args.time_limit,args.couple_families,args.output_name)
