"""Parallel fixed-membership searches with private state and exact final scoring.

Run on a fork-capable host. Read-only models are inherited, while each process
owns its caches, random generator, candidates and log. No netlist is changed.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import contextlib
import copy
import json
import math
import multiprocessing
from pathlib import Path
import random
import shutil
import time

from directed_search import Search, emit
from static_regions import LIMITS

_SEARCH = None


def load(path):
    return json.loads(path.read_text())


def dump(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def signature(plan, mids):
    return tuple(tuple(plan[m]['bounds']) for m in mids)


def choose_starts(records, mids, count):
    """Keep the best score, then spread starts across distinct die assignments."""
    ordered = sorted(records, key=lambda p: (p['components']['J'], p['tag']))
    selected = []; seen_slrs = set(); seen_regions = set()
    for p in ordered:
        slrs = tuple(tuple(p['regions'][m]['slrs']) for m in mids)
        if slrs in seen_slrs:
            continue
        selected.append(p); seen_slrs.add(slrs)
        seen_regions.add(signature(p['regions'], mids))
        if len(selected) == count:
            return selected
    for p in ordered:
        key = signature(p['regions'], mids)
        if key not in seen_regions:
            selected.append(p); seen_regions.add(key)
            if len(selected) == count:
                return selected
    while len(selected) < count:
        selected.append(ordered[len(selected) % len(ordered)])
    return selected


def worker(index, seed, start, steps):
    search = _SEARCH
    folder = search.run / 'workers' / f'w{index:02d}'
    folder.mkdir(parents=True, exist_ok=False)
    search.run = folder; search.trials = []; search.score_cache = {}
    started = time.monotonic(); mids = [m['module_id'] for m in search.modules]
    with (folder / 'search.log').open('w', buffering=1) as log, contextlib.redirect_stdout(log):
        dump(folder / 'status.json', dict(status='RUNNING', seed=seed, stage='initial_refinement', start=start['tag']))
        search.record('start', start['regions'], dict(seed=seed, original_start=start['tag']))
        chosen, history = search.refine(start['regions'], seed)
        first = search.record('coordinate', chosen, dict(seed=seed, history=history))
        rng = random.Random(seed); chosen = copy.deepcopy(first['regions'])
        best = copy.deepcopy(chosen); current = initial = best_J = first['components']['J']
        feasible = accepted = 0
        for step in range(steps):
            if step % 2000 == 0:
                dump(folder / 'status.json', dict(status='RUNNING', stage='annealing', seed=seed,
                     step=step, steps=steps, best_J=best_J, seconds=time.monotonic()-started))
            trial = dict(chosen); mode = rng.random()
            if mode < .18 and len(mids) > 1:
                a, b = rng.sample(mids, 2); trial[a], trial[b] = trial[b], trial[a]
            elif mode < .43 and len(mids) > 1:
                for mid in rng.sample(mids, 2):
                    trial[mid] = rng.choice(search.options[mid])
            elif mode < .55:
                slr = rng.randrange(4); group = [m for m in mids if chosen[m]['slrs'] == [slr]]
                if not group:
                    continue
                if rng.random() < .5:
                    group = rng.sample(group, rng.randint(1, len(group)))
                dx, dy = rng.choice([(1,0),(-1,0),(0,1),(0,-1),(0,4),(0,-4)])
                valid = True
                for mid in group:
                    x0,y0,x1,y1 = chosen[mid]['bounds']
                    bounds = (x0+dx,y0+dy,x1+dx,y1+dy)
                    if bounds not in search.lookup:
                        valid = False; break
                    trial[mid] = search.lookup[bounds]
                if not valid:
                    continue
            else:
                mid = rng.choice(mids)
                if rng.random() < .8:
                    bounds = list(chosen[mid]['bounds']); bounds[rng.randrange(4)] += rng.choice([-1,1])
                    if tuple(bounds) not in search.lookup:
                        continue
                    trial[mid] = search.lookup[tuple(bounds)]
                else:
                    trial[mid] = rng.choice(search.options[mid])
            if not search.legal(trial):
                continue
            feasible += 1; value = search.score(trial)['J']
            temperature = max(1e-12, initial*.05*(.0001/.05)**(step/max(1,steps-1)))
            if value <= current or rng.random() < math.exp(min(0., (current-value)/temperature)):
                chosen = trial; current = value; accepted += 1
            if value < best_J-1e-6:
                best = copy.deepcopy(trial); best_J = value
        stats = dict(seed=seed, steps=steps, feasible=feasible, accepted=accepted)
        search.record('anneal', best, stats)
        dump(folder / 'status.json', dict(status='RUNNING', seed=seed, stage='final_refinement', best_J=best_J))
        plan, history = search.refine(best, seed)
        refined = search.record('refined', plan, dict(**stats, history=history))
        for mapping, plan in search.permutations(refined['regions']):
            search.record('permutation_'+'_'.join(map(str,mapping)), plan, dict(mapping=mapping))
        result = min(search.trials, key=lambda p: (p['components']['J'],p['tag']))
        dump(folder / 'comparison.json', search.trials)
        dump(folder / 'status.json', dict(status='PASS', seed=seed, best_J=result['components']['J'],
             tag=result['tag'], seconds=time.monotonic()-started, **{k:v for k,v in stats.items() if k!='seed'}))
    return str(folder)


def solve(run, previous_candidates, workers=6, steps=36000, seeds=None):
    global _SEARCH
    if workers < 1 or steps < 1:
        raise ValueError('Workers and steps must be positive.')
    seeds = seeds if seeds is not None else [211+17*i for i in range(workers)]
    if len(seeds) != workers or len(set(seeds)) != workers:
        raise ValueError('Each worker requires one distinct seed.')
    started = time.monotonic(); search = Search(run); _SEARCH = search
    assert search.cfg['resource_limits'] == LIMITS
    assert not search.density_profiles
    mids = [m['module_id'] for m in search.modules]; seen = set()
    baseline = search.record('reference_current', search.old['regions'])
    seen.add(signature(baseline['regions'], mids))
    # Only region geometry is reused. All historic scores are discarded.
    for i,p in enumerate(load(previous_candidates)):
        if set(p['regions']) != set(mids):
            raise ValueError('Candidate memberships differ.')
        key = signature(p['regions'], mids)
        if key in seen or not search.legal(p['regions']):
            continue
        seen.add(key)
        search.record(f'rescored_{i}', p['regions'], dict(previous_tag=p['tag']))
    starts = choose_starts(search.trials, mids, workers)
    dump(run / 'parallel_starts.json', [dict(worker=i, seed=seed, start=p['tag'],
         components=p['components'], regions=p['regions']) for i,(seed,p) in enumerate(zip(seeds,starts))])
    dump(run / 'parallel_status.json', dict(status='RUNNING', workers=workers, steps_per_worker=steps,
         seeds=seeds, baseline=baseline['components'], imported_unique=len(seen)))
    with ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context('fork')) as pool:
        futures = {pool.submit(worker,i,seed,p,steps):i for i,(seed,p) in enumerate(zip(seeds,starts))}
        completed = []
        for future in as_completed(futures):
            folder = Path(future.result()); index = futures[future]
            completed.append(load(folder/'status.json'))
            # Scores returned by workers are checked in the parent process.
            for p in load(folder/'comparison.json'):
                if not search.legal(p['regions']):
                    raise ValueError('Worker produced an infeasible candidate.')
                check = search.score(p['regions'],True)
                assert math.isclose(check['J'],p['components']['J'],rel_tol=1e-12,abs_tol=1e-6)
                search.record(f'w{index:02d}_{p["tag"]}',p['regions'],p['extra'])
            dump(run/'parallel_status.json',dict(status='RUNNING',workers=workers,completed=completed,
                 best_J=min(p['components']['J'] for p in search.trials),seconds=time.monotonic()-started))
            emit(dict(stage='worker_complete',worker=index,**completed[-1]))
    best = min(search.trials,key=lambda p:(p['components']['J'],p['tag']))
    plan,history = search.refine(best['regions'],997)
    final = search.record('pooled_refined',plan,dict(parent=best['tag'],seed=997,history=history))
    for mapping,plan in search.permutations(final['regions']):
        search.record('pooled_permutation_'+'_'.join(map(str,mapping)),plan,dict(mapping=mapping))
    reference = baseline['regions']
    movement = lambda p:sum(abs(p['regions'][m]['center'][a]-reference[m]['center'][a]) for m in mids for a in [0,1])
    minimum = min(p['components']['J'] for p in search.trials)
    best = min((p for p in search.trials if p['components']['J']<=minimum+1e-6),key=lambda p:(movement(p),p['tag']))
    assert best['components']['J'] <= baseline['components']['J']+1e-6
    result = dict(best,objective=best['components']['J'],configuration=search.cfg,limits=LIMITS,
         normalized=False,candidate_stats=search.stats,total_module_crs=sum(r['area'] for r in best['regions'].values()),
         maximum_slrs_per_unit=max(len(r['slrs']) for r in best['regions'].values()),
         resource_distribution='capacity proportional; no routed fit',movement_from_reference=movement(best),
         runtime_seconds=time.monotonic()-started,parallel_workers=workers,seeds=seeds,steps_per_worker=steps,
         cumulative_path_coverage=search.paths.graph['coverage'] if search.paths else None,
         search_certificate='Reweighted existing candidate pool, independent parallel coordinate/annealing searches, pooled exact refinement and die permutations; no global optimum claim.',
         timing_validation='No placement or route; structural path risk only.')
    dump(run/'solution.json',result);dump(run/'comparison.json',search.trials)
    shutil.copytree(run/'input/export',run/'export');dump(run/'export/static_regions.json',result)
    dump(run/'parallel_status.json',dict(status='PASS',workers=workers,completed=sorted(completed,key=lambda p:p['seed']),
         before=baseline['components'],after=best['components'],seconds=result['runtime_seconds']))
    emit(dict(stage='parallel_complete',J=result['objective'],seconds=result['runtime_seconds']))
    return result


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run',type=Path)
    parser.add_argument('--previous-candidates',required=True,type=Path)
    parser.add_argument('--workers',type=int,default=6)
    parser.add_argument('--steps',type=int,default=36000)
    args=parser.parse_args()
    solve(args.run.resolve(),args.previous_candidates.resolve(),args.workers,args.steps)
