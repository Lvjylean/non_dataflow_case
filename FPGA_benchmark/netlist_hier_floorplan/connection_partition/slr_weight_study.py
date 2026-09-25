"""Fixed-membership SLR-distance sensitivity; never pins a module to a die."""
import copy
import json
import shutil
import sys
import time
from pathlib import Path

from directed_search import Search, emit
from directed_prepare import sha
from static_regions import LIMITS


def dump(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def at_weight(c, weight):
    return (c['x_span'] + c['y_span'] + c['directed_x'] + c['directed_y']
            + weight * (c['slr_span'] + c['directed_slr'])
            + 32 * c['branch_square'] + c['fixed_partition_cost'])


def initialize(run, reference):
    (run / 'input').mkdir()
    sources = [p for folder in ['export', 'implementation_input']
               for p in (reference / folder).rglob('*') if p.is_file()]
    sources += [reference / n for n in ['netmodel.pkl', 'directed.json', 'input/cr.tsv', 'solution.json']]
    hashes = {str(p): sha(p) for p in sources}
    shutil.copytree(reference / 'export', run / 'input/export')
    shutil.copy2(reference / 'input/cr.tsv', run / 'input/cr.tsv')
    shutil.copy2(reference / 'input/original_regions.json', run / 'input/original_regions.json')
    for n in ['netmodel.pkl', 'directed.json']:
        shutil.copy2(reference / n, run / n)
    previous = json.loads((reference / 'binding.json').read_text())
    previous.update(previous=str(reference), immutable_files=hashes,
                    scope='Fixed eleven members; global SLR-distance parameter study. No S01 die constraint; no P&R.')
    dump(run / 'binding.json', previous)
    for p, h in hashes.items():
        assert sha(Path(p)) == h


def preflight(run):
    search = Search(run)
    baseline = search.old['regions']
    pool = {}

    def keep(tag, chosen):
        key = tuple(tuple(chosen[m['module_id']]['bounds']) for m in search.modules)
        if key in pool or not search.legal(chosen):
            return
        pool[key] = dict(tag=tag, regions=copy.deepcopy(chosen), components=search.score(chosen))

    keep('reference_core', baseline)
    keep('original_core', search.original['regions'])
    counts = {}
    for slr in range(4):
        count = 0
        for j, region in enumerate(search.options['S01']):
            if region['slrs'] != [slr]:
                continue
            trial = dict(baseline, S01=region)
            if search.legal(trial):
                count += 1
                keep(f's01_only_{j}', trial)
        counts[str(slr)] = count
    # Bounded simultaneous relocation avoids declaring SLR2 impossible merely
    # because every other rectangle was frozen. S01 is not restricted to SLR2.
    for module in search.modules:
        mid = module['module_id']
        if mid == 'S01':
            continue
        trial = dict(baseline)
        trial[mid] = baseline['S01']
        for j, region in enumerate(search.options['S01']):
            trial['S01'] = region
            keep(f'exchange_{mid}_{j}', trial)
    weights = [4, 8, 16, 32]
    chosen = {}; sensitivity = []
    for weight in weights:
        best = min(pool.values(), key=lambda p: at_weight(p['components'], weight))
        row = dict(weight=weight, best_tag=best['tag'], J=at_weight(best['components'], weight),
                   S01=best['regions']['S01']['slrs'], S10=best['regions']['S10']['slrs'], by_S01_die={})
        for slr in range(4):
            eligible = [p for p in pool.values() if p['regions']['S01']['slrs'] == [slr]]
            if eligible:
                p = min(eligible, key=lambda p: at_weight(p['components'], weight))
                chosen[p['tag']] = p
                row['by_S01_die'][str(slr)] = dict(tag=p['tag'], J=at_weight(p['components'], weight))
        sensitivity.append(row)
    dump(run / 'preflight.json', dict(weights=weights, single_move_legal_counts=counts,
        evaluated_plans=len(pool), sensitivity=sensitivity, shortlist=list(chosen.values()),
        scope='Exact scores for baseline, single-S01 moves and simultaneous S01/other relocations; not a global optimum.'))
    emit(dict(stage='preflight', legal_single_moves=counts, plans=len(pool), sensitivity=sensitivity))


def solve(run, weight):
    variant = run / ('weight_' + str(weight))
    variant.mkdir()
    shutil.copytree(run / 'source', variant / 'source', ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copytree(run / 'input', variant / 'input')
    for n in ['netmodel.pkl', 'directed.json', 'binding.json']:
        shutil.copy2(run / n, variant / n)
    cfg = json.loads((variant / 'source/directed_config.json').read_text())
    cfg.update(slr_distance_weight=float(weight), mip_seconds=120,
               notes='Global SLR-distance sensitivity; all eleven module regions free. No per-module die preference or constraint. All other objective/resource/area coefficients unchanged.')
    dump(variant / 'source/directed_config.json', cfg)
    dump(variant / 'source/manifest.json', {p.name: sha(p) for p in (variant / 'source').iterdir()
        if p.is_file() and p.name != 'manifest.json'})
    search = Search(variant); started = time.time()
    search.netmodel._cache = {}
    search.record('baseline_current', search.old['regions'])
    search.record('baseline_original', search.original['regions'])
    for proposal in json.loads((run / 'preflight.json').read_text())['shortlist']:
        search.record('preflight_' + proposal['tag'], proposal['regions'])
    for oldrun in sorted(run.glob('weight_*')):
        if (oldrun / 'solution.json').exists():
            plan = json.loads((oldrun / 'solution.json').read_text())
            search.record('warm_' + oldrun.name, plan['regions'])
    best = min(search.trials, key=lambda p: p['components']['J'])
    starts = [best]
    for seed in search.cfg['mip_seeds']:
        chosen, status = search.mip(seed, best['regions'])
        if chosen:
            trial = search.record(f'mip_{seed}', chosen, status); starts.append(trial)
            if trial['components']['J'] < best['components']['J']:
                best = trial
    while len(starts) < len(search.cfg['local_seeds']):
        starts.append(best)
    for i, (start, seed) in enumerate(zip(starts, search.cfg['local_seeds'])):
        chosen, history = search.refine(start['regions'], seed)
        search.record(f'refined_{i}', chosen, dict(start=start['tag'], seed=seed, history=history))
    best = min(search.trials, key=lambda p: (p['components']['J'], p['components']['raw_far_pins'], p['tag']))
    result = dict(best, normalized=False, configuration=search.cfg, candidate_stats=search.stats, limits=LIMITS,
        total_module_crs=sum(r['area'] for r in best['regions'].values()),
        maximum_slrs_per_unit=max(len(r['slrs']) for r in best['regions'].values()),
        objective=best['components']['J'], runtime_seconds=time.time()-started,
        search_certificate='Best exact J among recorded feasible proposals; MIP bound/gap certify only the proposal surrogate. No global optimum claim.',
        timing_validation='Not run.', physical_model='Unnormalized all-net expected spans plus all directed sink-pin branches; no same-cycle path accumulation.')
    dump(variant / 'solution.json', result)
    dump(variant / 'comparison.json', [dict(tag=p['tag'], components=p['components'], extra=p['extra']) for p in search.trials])
    shutil.copytree(variant / 'input/export', variant / 'export')
    dump(variant / 'export/static_regions.json', result)
    emit(dict(stage='solved', weight=weight, selected=best['tag'], J=result['objective'],
              S01=result['regions']['S01']['slrs'], S10=result['regions']['S10']['slrs'], seconds=result['runtime_seconds']))


if __name__ == '__main__':
    action, directory, *args = sys.argv[1:]; root = Path(directory).resolve()
    if action == 'initialize': initialize(root, Path(args[0]))
    elif action == 'preflight': preflight(root)
    elif action == 'solve': solve(root, int(args[0]))
    else: raise ValueError(action)
