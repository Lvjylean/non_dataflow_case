"""Fixed-membership local floorplanning with 70% non-URAM resource limits."""
import copy
import hashlib
import json
import math
from pathlib import Path
import random
import shutil
import sys
import time

ROOT = Path(sys.argv[1]).resolve()


def load(path):
    return json.loads(path.read_text())


def dump(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False)+'\n')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    sys.path.insert(0,str(ROOT/'source'))
    import numpy as np
    from directed_search import Search,emit
    from static_regions import LIMITS,RESOURCES,overlap_audit
    search=Search(ROOT);search.netmodel._cache={};started=time.perf_counter()
    assert LIMITS==search.cfg['resource_limits']
    assert not search.density_profiles
    limits=np.array([LIMITS[r] for r in RESOURCES])
    mids=[m['module_id'] for m in search.modules]
    by_mid={m['module_id']:m for m in search.modules}
    reference=search.old['regions']
    refs=[(r['name'],load(ROOT/r['path'])['regions']) for r in load(ROOT/'search_references.json')]
    comparisons={}
    for name,regions in refs:
        occupancy=sum(search.occupancy(m,regions[m['module_id']]) for m in search.modules)
        comparisons[name]=dict(legal_under_70=search.legal(regions),components_at_w8=search.score(regions,True),
            peak_utilization={r:float(occupancy[:,i].max()) for i,r in enumerate(RESOURCES)},
            violations=[dict(cr=search.keys[c],resource=RESOURCES[r],utilization=float(occupancy[c,r]),limit=float(limits[r]))
                for c,r in zip(*np.where(occupancy>limits+1e-8))])
    dump(ROOT/'baseline_comparison.json',comparisons)
    emit(dict(stage='options_ready',options=search.stats,baselines={n:v['legal_under_70'] for n,v in comparisons.items()}))
    arrays={mid:np.stack([search.occupancy(by_mid[mid],r) for r in search.options[mid]]) for mid in mids}
    seeds=[];seen=set();repair_logs=[]
    def keep(tag,plan,extra):
        signature=tuple(tuple(plan[m]['bounds']) for m in mids)
        if signature in seen or not search.legal(plan):return
        seen.add(signature);record=search.record(tag,plan,extra);seeds.append(record)

    for name,plan in refs:
        keep('reference_'+name,plan,dict(kind='unchanged_reference_recomputed_at_current_settings'))

    # Repair old layouts by minimizing summed squared CR overflows. These
    # infeasible repair states never enter the final feasible candidate pool.
    for seed in [0,17,31,47,61,79]:
        rng=random.Random(seed);label,base=refs[seed%len(refs)];chosen=copy.deepcopy(base)
        history=[]
        for iteration in range(60):
            order=list(mids);rng.shuffle(order)
            density=sum(search.occupancy(by_mid[m],chosen[m]) for m in mids)
            for mid in order:
                old=search.occupancy(by_mid[mid],chosen[mid]);rest=density-old
                errors=np.maximum(0,arrays[mid]+rest-limits)
                violations=np.sum(errors*errors,axis=(1,2))
                best=float(violations.min());eligible=np.flatnonzero(violations<=best+1e-12)
                if iteration==0:
                    j=min(eligible,key=lambda j:(sum(abs(a-b) for a,b in zip(search.options[mid][j]['center'],base[mid]['center'])),search.options[mid][j]['area']))
                else:
                    shortlist=sorted(eligible,key=lambda j:search.options[mid][j]['area'])[:min(30,len(eligible))]
                    j=rng.choice(shortlist)
                chosen[mid]=search.options[mid][int(j)];density=rest+arrays[mid][j]
            v=float(np.square(np.maximum(0,density-limits)).sum());history.append(v)
            if search.legal(chosen):break
        repair_logs.append(dict(seed=seed,start=label,iterations=len(history),overflow_history=history,success=search.legal(chosen)))
        keep(f'repaired_{seed}',chosen,repair_logs[-1])
    # Sequential legal packing provides starts not tied to the old die labels.
    for seed in [101,117,131,147,161,179]:
        rng=random.Random(seed);chosen={};density=np.zeros((len(search.keys),len(RESOURCES)))
        order=sorted(mids,key=lambda m:(-by_mid[m]['URAM'],-by_mid[m]['LUT']))
        if seed%2 and len(order)>4:order=order[:4]+rng.sample(order[4:],len(order)-4)
        for mid in order:
            valid=np.flatnonzero(np.all(arrays[mid]+density<=limits+1e-8,axis=(1,2)))
            if not len(valid):break
            shortlist=sorted(valid,key=lambda j:(search.options[mid][j]['area'],rng.random()))[:40]
            j=rng.choice(shortlist);chosen[mid]=search.options[mid][int(j)];density+=arrays[mid][j]
        if len(chosen)==len(mids):keep(f'packed_{seed}',chosen,dict(seed=seed,kind='sequential_resource_feasible_packing'))
    dump(ROOT/'repair_log.json',repair_logs)
    if not seeds:raise RuntimeError('No feasible seed; no device-infeasibility conclusion.')
    starts=sorted(seeds,key=lambda p:p['components']['J'])[:3]
    refined=[]
    for seed,start in zip([0,17,31],starts):
        plan,history=search.refine(start['regions'],seed)
        refined.append(search.record(f'coordinate_{seed}',plan,dict(seed=seed,start=start['tag'],history=history)))
    for seed,start in zip([0,17,31],refined):
        rng=random.Random(seed);chosen=copy.deepcopy(start['regions']);current=initial=start['components']['J']
        best=copy.deepcopy(chosen);best_J=current;accepted=feasible=0;history=[]
        steps=search.cfg['anneal_steps_per_seed']
        for step in range(steps):
            trial=dict(chosen);mode=rng.random()
            if mode<.18 and len(mids)>1:
                a,b=rng.sample(mids,2);trial[a],trial[b]=trial[b],trial[a]
            elif mode<.42 and len(mids)>1:
                a,b=rng.sample(mids,2)
                for mid in [a,b]:trial[mid]=rng.choice(search.options[mid])
            else:
                mid=rng.choice(mids)
                if rng.random()<.7:
                    bounds=list(chosen[mid]['bounds']);bounds[rng.randrange(4)]+=rng.choice([-1,1])
                    if tuple(bounds) not in search.lookup:continue
                    trial[mid]=search.lookup[tuple(bounds)]
                else:trial[mid]=rng.choice(search.options[mid])
            if not search.legal(trial):continue
            feasible+=1;value=search.score(trial)['J']
            temperature=initial*.04*(.0002/.04)**(step/max(1,steps-1))
            if value<=current or rng.random()<math.exp(min(0,(current-value)/temperature)):
                chosen=trial;current=value;accepted+=1
            if value<best_J-1e-6:best=copy.deepcopy(trial);best_J=value
            if step%2000==0:
                history.append(dict(step=step,current_J=current,best_J=best_J))
                emit(dict(stage='anneal',seed=seed,step=step,best_J=best_J))
        search.record(f'anneal_{seed}',best,dict(seed=seed,steps=steps,feasible=feasible,accepted=accepted,history=history))
        plan,history=search.refine(best,seed)
        search.record(f'anneal_refined_{seed}',plan,dict(seed=seed,history=history))
    # Enumerate legal die relabelings of the strongest single-die candidates.
    for record in sorted(search.trials,key=lambda p:p['components']['J'])[:3]:
        for target,plan in search.permutations(record['regions']):
            signature=tuple(tuple(plan[m]['bounds']) for m in mids)
            if signature in seen:continue
            seen.add(signature);search.record('perm_'+str(len(seen)),plan,dict(parent=record['tag'],mapping=target))
    minimum=min(p['components']['J'] for p in search.trials)
    def movement(p):
        return sum(abs(p['regions'][m]['center'][a]-reference[m]['center'][a]) for m in mids for a in [0,1])
    best=min([p for p in search.trials if p['components']['J']<=minimum+1e-6],key=lambda p:(movement(p),p['tag']))
    result=dict(best,objective=best['components']['J'],configuration=search.cfg,limits=LIMITS,
        candidate_stats=search.stats,total_module_crs=sum(r['area'] for r in best['regions'].values()),
        maximum_slrs_per_unit=max(len(r['slrs']) for r in best['regions'].values()),normalized=False,
        resource_distribution='capacity proportional; no routed fit',runtime_seconds=time.perf_counter()-started,
        movement_from_reference=movement(best),tie_break='Within absolute J 1e-6: minimum summed center L1 movement from selected partition core, then tag.',
        search_certificate='Finite local search: resource-repaired and packed starts, three exact coordinate descents, 3x8000 annealing proposals, exact final refinement and legal die permutations. No MIP or global optimality proof.',
        timing_validation='Not run; no WNS prediction.')
    dump(ROOT/'solution.json',result);dump(ROOT/'comparison.json',search.trials)
    shutil.copytree(ROOT/'input/export',ROOT/'export');dump(ROOT/'export/static_regions.json',result)
    emit(dict(stage='complete',J=result['objective'],runtime_seconds=result['runtime_seconds'],regions={m:r['bounds'] for m,r in result['regions'].items()},peak=result['overlap']['maximum_utilization']))


if __name__=='__main__':main()
