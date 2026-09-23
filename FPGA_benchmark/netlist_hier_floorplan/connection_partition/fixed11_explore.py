"""Additional diverse starts and bounded joint-move annealing for the 70% case."""
import copy
import json
import math
from pathlib import Path
import random
import shutil
import sys
import time

ROOT=Path(sys.argv[1]).resolve()
sys.path.insert(0,str(ROOT/'source'))
from directed_search import Search,emit
from static_regions import LIMITS
load=lambda p:json.loads(p.read_text())
dump=lambda p,v:p.write_text(json.dumps(v,indent=2)+'\n')
search=Search(ROOT);search.netmodel._cache={};search.trials=load(ROOT/'comparison.json')
base=load(ROOT/'solution.json');shutil.copy2(ROOT/'solution.json',ROOT/'solution_initial.json')
started=time.perf_counter();mids=sorted(base['regions'])
for i,start in enumerate([p for p in list(search.trials) if p['tag'].startswith(('reference_','repaired_','packed_'))]):
    plan,history=search.refine(start['regions'],100+i)
    search.record('diverse_coordinate_'+str(i),plan,dict(start=start['tag'],seed=100+i,history=history))
starts=[];seen=set()
for p in sorted(search.trials,key=lambda p:p['components']['J']):
    key=tuple(tuple(p['regions'][m]['bounds']) for m in mids)
    if key in seen:continue
    seen.add(key);starts.append(p)
    if len(starts)==8:break
for i,start in enumerate(starts):
    seed=211+i*17;rng=random.Random(seed);chosen=copy.deepcopy(start['regions'])
    best=copy.deepcopy(chosen);current=initial=best_J=start['components']['J']
    feasible=accepted=0;history=[];steps=24000
    for step in range(steps):
        trial=dict(chosen);mode=rng.random()
        if mode<.18 and len(mids)>1:
            a,b=rng.sample(mids,2);trial[a],trial[b]=trial[b],trial[a]
        elif mode<.43 and len(mids)>1:
            for m in rng.sample(mids,2):trial[m]=rng.choice(search.options[m])
        elif mode<.55:
            s=rng.randrange(4);group=[m for m in mids if chosen[m]['slrs']==[s]]
            if not group:continue
            if rng.random()<.5:group=rng.sample(group,rng.randint(1,len(group)))
            dx,dy=rng.choice([(1,0),(-1,0),(0,1),(0,-1),(0,4),(0,-4)])
            valid=True
            for m in group:
                x0,y0,x1,y1=chosen[m]['bounds'];bounds=(x0+dx,y0+dy,x1+dx,y1+dy)
                if bounds not in search.lookup:valid=False;break
                trial[m]=search.lookup[bounds]
            if not valid:continue
        else:
            m=rng.choice(mids)
            if rng.random()<.8:
                bounds=list(chosen[m]['bounds']);bounds[rng.randrange(4)]+=rng.choice([-1,1])
                if tuple(bounds) not in search.lookup:continue
                trial[m]=search.lookup[tuple(bounds)]
            else:trial[m]=rng.choice(search.options[m])
        if not search.legal(trial):continue
        feasible+=1;value=search.score(trial)['J']
        temperature=initial*.05*(.0001/.05)**(step/(steps-1))
        if value<=current or rng.random()<math.exp(min(0,(current-value)/temperature)):
            chosen=trial;current=value;accepted+=1
        if value<best_J-1e-6:best=copy.deepcopy(trial);best_J=value
    stats=dict(seed=seed,start=start['tag'],steps=steps,feasible=feasible,accepted=accepted,
        temperature='initial J * 0.05 to initial J * 0.0001; geometric cooling')
    search.record('joint_anneal_'+str(i),best,stats)
    plan,history=search.refine(best,seed)
    search.record('joint_refined_'+str(i),plan,dict(**stats,history=history))
for record in sorted(search.trials,key=lambda p:p['components']['J'])[:4]:
    for target,plan in search.permutations(record['regions']):
        key=tuple(tuple(plan[m]['bounds']) for m in mids)
        if key in seen:continue
        seen.add(key);search.record('final_permutation_'+str(len(seen)),plan,dict(parent=record['tag'],mapping=target))
ref=search.old['regions']
movement=lambda p:sum(abs(p['regions'][m]['center'][a]-ref[m]['center'][a]) for m in mids for a in [0,1])
minimum=min(p['components']['J'] for p in search.trials)
best=min([p for p in search.trials if p['components']['J']<=minimum+1e-6],key=lambda p:(movement(p),p['tag']))
result=dict(base,**best,objective=best['components']['J'],
    total_module_crs=sum(r['area'] for r in best['regions'].values()),
    maximum_slrs_per_unit=max(len(r['slrs']) for r in best['regions'].values()),
    movement_from_reference=movement(best),runtime_seconds=base['runtime_seconds']+time.perf_counter()-started,
    search_certificate='Resource-repaired and packed starts; all feasible starting-layout coordinate descents; 3x8000 initial and 8x24000 joint annealing proposals, final exact local refinement and legal die permutations. No MIP or global optimality proof.')
dump(ROOT/'solution.json',result);dump(ROOT/'export/static_regions.json',result);dump(ROOT/'comparison.json',search.trials)
emit(dict(stage='exploration_complete',J=result['objective'],initial_J=base['objective'],tag=best['tag'],
    seconds=result['runtime_seconds'],peak=result['overlap']['maximum_utilization'],
    regions={m:r['bounds'] for m,r in result['regions'].items()}))
