"""Fixed eleven modules: all directed sink-pin costs, joint proposals and exact refinement."""
import copy
import itertools
import json
import pickle
import random
import shutil
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

from balanced_regions import options_for
from static_regions import RESOURCES,LIMITS,load_device,all_rectangles,fits,overlap_audit
from directed_model import DirectedModel
from routed_density import resource_probabilities


def emit(data):print(json.dumps(data),flush=True)


class Search:
    def __init__(self,run):
        self.run=run;self.cfg=json.loads((run/'source/directed_config.json').read_text())
        self.meta=json.loads((run/'input/export/modules.json').read_text());self.modules=self.meta['modules']
        self.device=load_device(run/'input/cr.tsv')
        self.old=json.loads((run/'input/export/static_regions.json').read_text())
        self.original=json.loads((run/'input/original_regions.json').read_text())
        self.data=json.loads((run/'directed.json').read_text())
        with (run/'netmodel.pkl').open('rb') as f:self.netmodel=pickle.load(f)
        self.directed=DirectedModel(self.data,self.device,self.cfg)
        self.fixed_cost=json.loads((run/'binding.json').read_text())['fixed_partition_cost']
        self.rectangles=all_rectangles(self.device)
        self.lookup={tuple(r['bounds']):r for r in self.rectangles}
        self.options={};self.stats={}
        for m in self.modules:
            mid=m['module_id'];self.options[mid],self.stats[mid]=options_for(m,self.rectangles,self.cfg)
        self.keys=list(self.device);self.index={c:i for i,c in enumerate(self.keys)}
        self.resource_mask=np.array([[self.device[c]['resources'][r]>0 for r in RESOURCES] for c in self.keys])
        self.density_cache={};self.score_cache={};self.trials=[];self.unary=None
        profile_path=self.cfg.get('routed_density_profile')
        self.density_profiles={}
        if profile_path:
            self.density_profiles=json.loads((run/profile_path).read_text())['modules']

    def region(self,mid,region):
        profile=self.density_profiles.get(mid)
        return dict(region,density_profile=profile) if profile else region

    def occupancy(self,m,r):
        r=self.region(m['module_id'],r)
        key=(m['module_id'],tuple(r['bounds']))
        if key not in self.density_cache:
            density=np.zeros((len(self.keys),len(RESOURCES)))
            for ri,resource in enumerate(RESOURCES):
                probabilities=resource_probabilities(r,self.device,resource)
                for c in r['crs']:
                    cap=self.device[c]['resources'][resource]
                    if cap:density[self.index[c],ri]=m[resource]*probabilities[c]/cap
            self.density_cache[key]=density
        return self.density_cache[key]

    def legal(self,chosen):
        if any(not fits(m,chosen[m['module_id']]) or chosen[m['module_id']]['area'] > self.stats[m['module_id']]['minimum_crs']*self.cfg['region_max_area_factor']+self.cfg['region_max_area_extra_crs'] for m in self.modules):return False
        density=sum(self.occupancy(m,chosen[m['module_id']]) for m in self.modules)
        return not np.any(density>np.array([LIMITS[r] for r in RESOURCES])+1e-8)

    def score(self,chosen,details=False):
        chosen={mid:self.region(mid,r) for mid,r in chosen.items()}
        key=tuple(tuple(chosen[m['module_id']]['bounds']) for m in self.modules)
        if key in self.score_cache and not details:return self.score_cache[key]
        internal={f'P{i:02d}':chosen[m['module_id']] for i,m in enumerate(self.modules)}
        base=self.netmodel.components(internal,self.cfg['slr_distance_weight'])
        directed=self.directed.components(chosen,details)
        result=dict(base,**directed,fixed_partition_cost=self.fixed_cost)
        result['old_J']=base['physical_cost']+self.fixed_cost
        result['J']=result['old_J']+directed['directed_term']+directed['branch_square_term']
        if not details:self.score_cache[key]=result
        return result

    def record(self,tag,chosen,extra=None):
        chosen={mid:self.region(mid,r) for mid,r in chosen.items()}
        assert self.legal(chosen)
        comp=self.score(chosen,True);audit=overlap_audit(self.modules,chosen,self.device)
        record=dict(tag=tag,regions=copy.deepcopy(chosen),components=comp,overlap=audit,
                    families=self.directed.family_audit(chosen),extra=extra or {},status='feasible')
        self.trials.append(record)
        folder=self.run/'candidates';folder.mkdir(exist_ok=True)
        (folder/(tag+'.json')).write_text(json.dumps(record,indent=2)+'\n')
        emit(dict(stage='candidate',tag=tag,J=comp['J'],old_J=comp['old_J'],
                  branch_square=comp['branch_square'],raw_far_pins=comp['raw_far_pins']))
        return record

    def permutations(self,original):
        if any(len(r['slrs'])!=1 for r in original.values()):return
        used=sorted({r['slrs'][0] for r in original.values()})
        for target in itertools.permutations(range(4),len(used)):
            mapping=dict(zip(used,target));chosen={}
            for mid,r in original.items():
                x0,y0,x1,y1=r['bounds'];delta=4*(mapping[r['slrs'][0]]-r['slrs'][0])
                new=self.lookup.get((x0,y0+delta,x1,y1+delta))
                if new is None:break
                chosen[mid]=new
            if len(chosen)==11 and self.legal(chosen):yield target,chosen

    def mip(self,seed,warm):
        import gurobipy as gp
        from gurobipy import GRB
        if self.unary is None:
            self.unary={m['module_id']:[self.netmodel.internal_region_cost(i,self.region(m['module_id'],r),self.cfg['slr_distance_weight'])+self.directed.internal_cost(i,self.region(m['module_id'],r))
                for r in self.options[m['module_id']]] for i,m in enumerate(self.modules)}
        model=gp.Model('fixed11_directed_region_proposal');model.Params.OutputFlag=0
        model.Params.Threads=2;model.Params.Seed=seed;model.Params.TimeLimit=self.cfg['mip_seconds']
        model.Params.MIPGap=.03
        z={m:model.addVars(len(rs),vtype=GRB.BINARY,name=m) for m,rs in self.options.items()}
        for m in z:
            model.addConstr(z[m].sum()==1)
            for j,r in enumerate(self.options[m]):z[m][j].Start=int(r['bounds']==warm[m]['bounds'])
        for c,d in self.device.items():
            for resource in RESOURCES:
                if not d['resources'][resource]:continue
                terms=[]
                for m in self.modules:
                    if not m[resource]:continue
                    mid=m['module_id']
                    terms.extend(z[mid][j]*self.occupancy(m,r)[self.index[c],RESOURCES.index(resource)]
                                 for j,r in enumerate(self.options[mid]) if c in r['crs'])
                if terms:model.addConstr(gp.quicksum(terms)<=LIMITS[resource])
        points={m:[gp.quicksum(z[m][j]*(r['center'][a] if a<2 else r['slr_center'])
                 for j,r in enumerate(rs)) for a in range(3)] for m,rs in self.options.items()}
        n=len(RESOURCES)
        pair_weights=Counter()
        for e in self.data['pairs']:
            a,b=e['source'],e['sink']
            if a//n!=b//n:pair_weights[tuple(sorted((a,b)))]+=e['weight']
        roles=sorted({a for pair in pair_weights for a in pair})
        means={}
        for slot in roles:
            mid=f'S{slot//n:02d}';ri=slot%n;values=[]
            for region in self.options[mid]:
                table,_=self.directed.profile(self.region(mid,region));cdf=table[ri];x,y,s=self.directed.dimensions
                values.append((x-cdf[:x].sum(),y-cdf[x:x+y].sum(),s-cdf[x+y:].sum()))
            means[slot]=[gp.quicksum(z[mid][j]*float(v[a]) for j,v in enumerate(values)) for a in range(3)]
        absolute={}
        def distance(a,b,axis):
            if a==b:return 0.
            key=(tuple(sorted((a,b))),axis)
            if key not in absolute:
                v=model.addVar(lb=0)
                model.addConstr(v>=means[a][axis]-means[b][axis]);model.addConstr(v>=means[b][axis]-means[a][axis])
                absolute[key]=v
            return absolute[key]
        terms=[];pairs=Counter()
        for e in self.meta['connections']:pairs[tuple(sorted((e['source'],e['sink'])))]+=e['weighted_nets']
        for (a,b),w in pairs.items():
            for axis,factor in enumerate((1,1,self.cfg['slr_distance_weight'])):
                v=model.addVar(lb=0);model.addConstr(v>=points[a][axis]-points[b][axis]);model.addConstr(v>=points[b][axis]-points[a][axis])
                terms.append(w*factor*v)
        terms.extend(z[m][j]*v for m,vs in self.unary.items() for j,v in enumerate(vs))
        quadratic=[]
        for (a,b),weight in pair_weights.items():
            terms.extend(self.cfg['directed_weight']*weight*factor*distance(a,b,axis)
                         for axis,factor in enumerate((1,1,self.cfg['slr_distance_weight'])))
            excess=model.addVar(lb=0);model.addConstr(excess>=distance(a,b,2)-1)
            quadratic.append(self.cfg['branch_square_weight']*weight*excess*excess)
        model.setObjective(gp.quicksum(terms)+gp.quicksum(quadratic),GRB.MINIMIZE)
        emit(dict(stage='mip_started',seed=seed,seconds=self.cfg['mip_seconds']))
        model.optimize()
        status=dict(seed=seed,status=int(model.Status),runtime=model.Runtime,solutions=model.SolCount,
             interpretation='Centroid/pair surrogate seed only; bound/gap do not certify the full static J.')
        if not model.SolCount:return None,status
        status.update(objective=model.ObjVal,bound=model.ObjBound,gap=model.MIPGap)
        chosen={m:rs[max(range(len(rs)),key=lambda j:z[m][j].X)] for m,rs in self.options.items()}
        return chosen,status

    def refine(self,initial,seed):
        chosen=copy.deepcopy(initial);rng=random.Random(seed);history=[]
        current=self.score(chosen)['J']
        for iteration in range(self.cfg['local_rounds']):
            moved=0;order=list(self.modules);rng.shuffle(order)
            for m in order:
                mid=m['module_id'];old=chosen[mid];opts=self.options[mid]
                pool=range(len(opts))
                best=old;best_cost=current
                for j in sorted(pool):
                    chosen[mid]=opts[j]
                    if not self.legal(chosen):continue
                    value=self.score(chosen)['J']
                    if value<best_cost-1e-7:best=opts[j];best_cost=value
                chosen[mid]=best
                if best_cost<current-1e-7:current=best_cost;moved+=1
                emit(dict(stage='refine_module',seed=seed,iteration=iteration,module=mid,J=current))
            # Joint swaps avoid some capacity-blocked one-module moves.
            for a,b in itertools.combinations(self.modules,2):
                ma,mb=a['module_id'],b['module_id'];ra,rb=chosen[ma],chosen[mb]
                chosen[ma],chosen[mb]=rb,ra
                if self.legal(chosen) and self.score(chosen)['J']<current-1e-7:
                    current=self.score(chosen)['J'];moved+=1
                else:chosen[ma],chosen[mb]=ra,rb
            history.append(dict(iteration=iteration,moves=moved,J=current))
            emit(dict(stage='refine',seed=seed,**history[-1]))
            if not moved:break
        return chosen,history

    def solve(self):
        started=time.time()
        rejected=[]
        for tag,plan in [('baseline_current',self.old),('baseline_original',self.original)]:
            if self.legal(plan['regions']):self.record(tag,plan['regions'])
            else:
                rejected.append(tag)
                emit(dict(stage='baseline_infeasible_under_current_density',tag=tag))
        seen={tuple(tuple(r['regions'][m['module_id']]['bounds']) for m in self.modules) for r in self.trials}
        for label,plan in [('current',self.old),('original',self.original)]:
            for target,chosen in self.permutations(plan['regions']):
                key=tuple(tuple(chosen[m['module_id']]['bounds']) for m in self.modules)
                if key in seen:continue
                seen.add(key);self.record(label+'_permutation_'+'_'.join(map(str,target)),chosen)
        best_perm=min(self.trials,key=lambda r:r['components']['J']) if self.trials else None
        best=best_perm
        proposals=[]
        for seed in self.cfg['mip_seeds']:
            chosen,status=self.mip(seed,best['regions'] if best else self.old['regions'])
            if chosen:
                trial=self.record(f'mip_{seed}',chosen,status);proposals.append(trial)
                if best is None or trial['components']['J']<best['components']['J']:best=trial
        if best is None:
            result=dict(status='no_feasible_candidate',configuration=self.cfg,
                        rejected_baselines=rejected,runtime_seconds=time.time()-started,
                        interpretation='No feasible proposal found; no device-infeasibility certificate.')
            (self.run/'solution.json').write_text(json.dumps(result,indent=2)+'\n')
            emit(result);return
        starts=[best_perm or best]+sorted(proposals,key=lambda r:r['components']['J'])
        while len(starts)<len(self.cfg['local_seeds']):starts.append(best)
        for i,(start,seed) in enumerate(zip(starts,self.cfg['local_seeds'])):
            chosen,history=self.refine(start['regions'],seed)
            self.record(f'refined_{i}',chosen,dict(start=start['tag'],seed=seed,history=history))
        best=min(self.trials,key=lambda r:(r['components']['J'],r['components']['raw_far_pins'],r['tag']))
        result=dict(best,normalized=False,configuration=self.cfg,candidate_stats=self.stats,limits=LIMITS,
            rejected_baselines=rejected,
            resource_distribution='bilinear routed density mixed with capacity prior' if self.density_profiles else 'capacity proportional',
            total_module_crs=sum(r['area'] for r in best['regions'].values()),
            maximum_slrs_per_unit=max(len(r['slrs']) for r in best['regions'].values()),
            objective=best['components']['J'],runtime_seconds=time.time()-started,
            search_certificate='Best exact static J among recorded proposals; no full-J global optimality claim.',
            timing_validation='Not run; no predicted WNS is asserted.',
            physical_model='Original all-net expected spans plus all modeled directed sink-pin expected distance and E[(single-branch boundaries-1)_+^2]. No path accumulation.')
        (self.run/'solution.json').write_text(json.dumps(result,indent=2)+'\n')
        summary=[dict(tag=r['tag'],components=r['components'],families=r['families'],extra=r['extra']) for r in self.trials]
        (self.run/'comparison.json').write_text(json.dumps(summary,indent=2)+'\n')
        shutil.copytree(self.run/'input/export',self.run/'export')
        (self.run/'export/static_regions.json').write_text(json.dumps(result,indent=2)+'\n')
        emit(dict(stage='solved',selected=best['tag'],J=result['objective'],seconds=result['runtime_seconds']))


if __name__=='__main__':Search(Path(sys.argv[1])).solve()
