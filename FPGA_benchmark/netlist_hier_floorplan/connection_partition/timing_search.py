"""Joint proposals and exact static-J refinement for eleven frozen modules."""
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
from timing_model import CriticalModel


def emit(data):print(json.dumps(data),flush=True)


class Search:
    def __init__(self,run):
        self.run=run;self.cfg=json.loads((run/'source/timing_floorplan_config.json').read_text())
        self.meta=json.loads((run/'input/export/modules.json').read_text());self.modules=self.meta['modules']
        self.device=load_device(run/'input/cr.tsv')
        self.old=json.loads((run/'input/export/static_regions.json').read_text())
        self.feedback=json.loads((run/'feedback.json').read_text())
        with (run/'netmodel.pkl').open('rb') as f:self.netmodel=pickle.load(f)
        self.critical=CriticalModel(self.feedback,self.device,self.cfg)
        self.fixed_cost=self.old['objective']-self.old['components']['physical_cost']
        self.rectangles=all_rectangles(self.device)
        self.lookup={tuple(r['bounds']):r for r in self.rectangles}
        self.options={};self.stats={}
        for m in self.modules:
            mid=m['module_id'];self.options[mid],self.stats[mid]=options_for(m,self.rectangles,self.cfg)
        self.keys=list(self.device);self.index={c:i for i,c in enumerate(self.keys)}
        self.resource_mask=np.array([[self.device[c]['resources'][r]>0 for r in RESOURCES] for c in self.keys])
        self.density_cache={};self.score_cache={};self.trials=[];self.unary=None

    def occupancy(self,m,r):
        key=(m['module_id'],tuple(r['bounds']))
        if key not in self.density_cache:
            density=np.zeros((len(self.keys),len(RESOURCES)))
            ratios=np.array([m[t]/r['capacity'][t] if r['capacity'][t] else 0 for t in RESOURCES])
            ids=[self.index[c] for c in r['crs']]
            density[ids]=self.resource_mask[ids]*ratios
            self.density_cache[key]=density
        return self.density_cache[key]

    def legal(self,chosen):
        if any(not fits(m,chosen[m['module_id']]) for m in self.modules):return False
        density=sum(self.occupancy(m,chosen[m['module_id']]) for m in self.modules)
        return not np.any(density>np.array([LIMITS[r] for r in RESOURCES])+1e-8)

    def score(self,chosen,details=False):
        key=tuple(tuple(chosen[m['module_id']]['bounds']) for m in self.modules)
        if key in self.score_cache and not details:return self.score_cache[key]
        internal={f'P{i:02d}':chosen[m['module_id']] for i,m in enumerate(self.modules)}
        base=self.netmodel.components(internal,self.cfg['slr_distance_weight'])
        timing=self.critical.components(chosen,details)
        result=dict(base,**timing,fixed_partition_cost=self.fixed_cost)
        result['old_J']=base['physical_cost']+self.fixed_cost
        result['J']=result['old_J']+timing['critical_connection_term']+timing['path_square_term']
        if not details:self.score_cache[key]=result
        return result

    def record(self,tag,chosen,extra=None):
        assert self.legal(chosen)
        comp=self.score(chosen,True);audit=overlap_audit(self.modules,chosen,self.device)
        record=dict(tag=tag,regions=copy.deepcopy(chosen),components=comp,overlap=audit,
                    broadcast=self.critical.broadcast(chosen),extra=extra or {},status='feasible')
        self.trials.append(record)
        folder=self.run/'candidates';folder.mkdir(exist_ok=True)
        (folder/(tag+'.json')).write_text(json.dumps(record,indent=2)+'\n')
        emit(dict(stage='candidate',tag=tag,J=comp['J'],old_J=comp['old_J'],
                  path_square=comp['weighted_path_square'],broadcast_far=record['broadcast']['expected_far_sink_pins']))
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
            self.unary={m['module_id']:[self.netmodel.internal_region_cost(i,r,self.cfg['slr_distance_weight'])
                for r in self.options[m['module_id']]] for i,m in enumerate(self.modules)}
        model=gp.Model('fixed11_timing_region_proposal');model.Params.OutputFlag=0
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
                    terms.extend(z[mid][j]*m[resource]/r['capacity'][resource]
                                 for j,r in enumerate(self.options[mid]) if c in r['crs'])
                if terms:model.addConstr(gp.quicksum(terms)<=LIMITS[resource])
        points={m:[gp.quicksum(z[m][j]*(r['center'][a] if a<2 else r['slr_center'])
                 for j,r in enumerate(rs)) for a in range(3)] for m,rs in self.options.items()}
        roles=sorted({(m,r) for a in self.critical.edges for m,r in (a[:2],a[2:])})
        means={}
        for m,r in roles:
            values=[]
            for region in self.options[m]:
                cdf,_=self.critical.profile(region,r);x,y,s=self.critical.dimensions
                values.append((x-cdf[:x].sum(),y-cdf[x:x+y].sum(),s-cdf[x+y:].sum()))
            means[m,r]=[gp.quicksum(z[m][j]*float(v[a]) for j,v in enumerate(values)) for a in range(3)]
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
        for (ma,ra,mb,rb),q in self.critical.edges.items():
            terms.extend(self.cfg['critical_distance_weight']*q*factor*distance((ma,ra),(mb,rb),axis)
                         for axis,factor in enumerate((1,1,self.cfg['slr_distance_weight'])))
        quadratic=[]
        for roles,q in self.critical.paths.items():
            n=gp.quicksum(distance(a[:2],b[:2],2) for a,b in zip(roles,roles[1:]))
            excess=model.addVar(lb=0);model.addConstr(excess>=n-1)
            quadratic.append(self.cfg['path_square_weight']*q*excess*excess)
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
                pool=set(rng.sample(range(len(opts)),min(len(opts),self.cfg['local_options'])))
                pool.update(sorted(range(len(opts)),key=lambda j:(opts[j]['area'],opts[j]['bounds']))[:8])
                # Include nearby CR changes and translations by complete die heights.
                x0,y0,x1,y1=old['bounds']
                nearby={(x0+dx,y0+dy,x1+dx,y1+dy) for dx in (-1,0,1) for dy in (-8,-4,-1,0,1,4,8)}
                for j,r in enumerate(opts):
                    if tuple(r['bounds']) in nearby:pool.add(j)
                best=old;best_cost=current
                for j in sorted(pool):
                    chosen[mid]=opts[j]
                    if not self.legal(chosen):continue
                    value=self.score(chosen)['J']
                    if value<best_cost-1e-7:best=opts[j];best_cost=value
                chosen[mid]=best
                if best_cost<current-1e-7:current=best_cost;moved+=1
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
        started=time.time();baseline=self.record('baseline',self.old['regions'])
        assert abs(baseline['components']['old_J']-self.old['objective'])<1e-6
        for target,chosen in self.permutations(self.old['regions']):
            if chosen==self.old['regions']:continue
            self.record('die_permutation_'+'_'.join(map(str,target)),chosen)
        best=min(self.trials,key=lambda r:r['components']['J'])
        best_perm=copy.deepcopy(best)
        for seed in self.cfg['mip_seeds']:
            chosen,status=self.mip(seed,best['regions'])
            if chosen:
                trial=self.record(f'mip_{seed}',chosen,status)
                if trial['components']['J']<best['components']['J']:best=trial
        starts=[best_perm,best]
        for i,(start,seed) in enumerate(zip(starts,self.cfg['local_seeds'])):
            chosen,history=self.refine(start['regions'],seed)
            self.record(f'refined_{i}',chosen,dict(start=start['tag'],history=history))
        best=min(self.trials,key=lambda r:(r['components']['J'],r['broadcast']['expected_far_sink_pins'],r['tag']))
        result=dict(best,normalized=False,configuration=self.cfg,candidate_stats=self.stats,limits=LIMITS,
            total_module_crs=sum(r['area'] for r in best['regions'].values()),
            maximum_slrs_per_unit=max(len(r['slrs']) for r in best['regions'].values()),
            objective=best['components']['J'],runtime_seconds=time.time()-started,
            search_certificate='Best exact static J among recorded proposals; no full-J global optimality claim.',
            timing_validation='Not run; no predicted WNS is asserted.',
            physical_model='Original all-net expected spans plus critical expected Manhattan distance and E[(n-1)_+^2]; independent capacity-weighted atoms.')
        (self.run/'solution.json').write_text(json.dumps(result,indent=2)+'\n')
        summary=[dict(tag=r['tag'],**{k:r['components'][k] for k in ['J','old_J','physical_cost','critical_connection_distance','weighted_path_square','path_expected_over_one']},
                      broadcast_far=r['broadcast']['expected_far_sink_pins']) for r in self.trials]
        (self.run/'comparison.json').write_text(json.dumps(summary,indent=2)+'\n')
        shutil.copytree(self.run/'input/export',self.run/'export')
        (self.run/'export/static_regions.json').write_text(json.dumps(result,indent=2)+'\n')
        emit(dict(stage='solved',selected=best['tag'],J=result['objective'],seconds=result['runtime_seconds']))


if __name__=='__main__':Search(Path(sys.argv[1])).solve()
