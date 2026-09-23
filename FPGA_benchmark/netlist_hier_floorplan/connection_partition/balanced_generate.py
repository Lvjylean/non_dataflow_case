"""Generate functional-core-aware alternatives from an immutable graph cache."""
import argparse
import json
import math
import multiprocessing as mp
from collections import Counter
from pathlib import Path

import partition as base
from improve import (load_context, logical_cores, save_candidate, labels_for,
                     objective, soft_edges, digest)


# On Linux the workers inherit the loaded graph copy-on-write. Each KaHyPar
# task writes a distinct tag; only the parent process writes candidate files.
_RUN = _DATA = _AUGMENTED = _BASELINE = _CONFIG = _WEIGHTS = None


def boundary_fraction(data, vertices, children):
    local = {a: i for i, group in enumerate(children) for a in group}
    volume = boundary = 0
    for edge, weight in data['edges']:
        touched = {local[a] for a in edge if a in local}
        if touched:
            volume += weight
            boundary += weight * (len(touched) - 1)
    return dict(incident_weight=volume/4, added_local_km1=boundary/4,
                fraction=boundary/volume if volume else 0)


def split_task(task):
    kind, parent, seed = task
    vertices = _BASELINE['groups'][parent]
    tag = f'split_p{parent}_s{seed}' if kind == 'uniform' else f'resource_p{parent}_s{seed}'
    saved = _RUN/'candidates'/tag/'groups.json'
    if saved.exists():
        groups = json.loads(saved.read_text())
        children = [g for g in groups
                    if g and all(_BASELINE['membership'][a] == parent for a in g)]
        assert {a for group in children for a in group} == set(vertices)
        return task, children, boundary_fraction(_DATA, vertices, children), True
    n = sum(_WEIGHTS[a] for a in vertices)
    if kind == 'uniform':
        upper = math.ceil(_CONFIG['split_max_parent_fraction']*n)
        if len(vertices) < 2 or max(_WEIGHTS[a] for a in vertices) > upper:
            return task, [vertices], dict(fraction=0), False
        pieces, weights = 2, _WEIGHTS
    else:
        demand = base.demand_of(_DATA, vertices)
        resource = max(('DSP', 'BRAM18', 'URAM'),
                       key=lambda r: demand[r]/base.SLR_CAPS[r])
        pieces = max(2, math.ceil(demand[resource]/base.SLR_CAPS[resource]))
        scale = n+1
        weights = {a: _DATA['atom_resources'][a].get(resource, 0)*scale+_WEIGHTS[a]
                   for a in vertices}
        upper = base.SLR_CAPS[resource]*scale+n
    children = base.run_kahypar(_RUN, _AUGMENTED, vertices, pieces,
                                [upper]*pieces, weights, tag, seed)
    assert len(children) == pieces
    return task, children, boundary_fraction(_DATA, vertices, children), False


def main(run, previous=None, workers=1):
    global _RUN, _DATA, _AUGMENTED, _BASELINE, _CONFIG, _WEIGHTS
    if workers < 1:
        raise ValueError('workers must be positive')
    if workers > 1 and 'fork' not in mp.get_all_start_methods():
        raise RuntimeError('parallel KaHyPar generation requires the fork start method')
    cfg = json.loads((run/'source/balanced_config.json').read_text())
    data, _, baseline, reference = load_context(run)
    cores = logical_cores(data, cfg['core_min_cells'], cfg['core_max_cells'],
                          cfg['core_min_cohesion'])
    (run/'cores.json').write_text(json.dumps(cores)+'\n')
    total_weight = sum(w for _, w in data['edges'])/4
    binding = dict(input_dcp=reference['input_dcp'], input_sha256=reference['input_sha256'],
                   graph_sha256=digest(run/'graph.pkl'), device_sha256=digest(run/'cr.tsv'),
                   config_sha256=digest(run/'source/balanced_config.json'),
                   all_net_weight=total_weight, cores=len(cores),
                   core_cells=sum(c['cells'] for c in cores))
    (run/'binding.json').write_text(json.dumps(binding, indent=2)+'\n')
    base.log('balanced_input', **binding)
    seen = set()
    records = []

    def save(name, groups, detail):
        signature = tuple(sorted(tuple(sorted(g)) for g in groups))
        if signature in seen:
            return None
        seen.add(signature)
        if (run/'candidates'/name/'summary.json').exists():
            stored = json.loads((run/'candidates'/name/'groups.json').read_text())
            assert stored == groups
            s = json.loads((run/'candidates'/name/'summary.json').read_text())
            records.append(dict(name=name, **s['metrics']))
            return name
        s = save_candidate(run, name, data, groups, cores, baseline['membership'], detail)
        labels = labels_for(data, groups)
        loss = objective(soft_edges(cores, cfg['core_soft_strength']), labels)[0]
        s['metrics']['logical_core_loss'] = loss
        s['metrics']['added_km1'] = s['metrics']['weighted_km1']-baseline['weighted_km1']
        s['metrics']['global_added_fraction'] = s['metrics']['added_km1']/total_weight
        s['metrics']['maximum_local_split_fraction'] = detail.get('maximum_local_split_fraction', 0)
        (run/'candidates'/name/'summary.json').write_text(json.dumps(s, indent=2)+'\n')
        records.append(dict(name=name, **s['metrics']))
        (run/'generation_summary.json').write_text(json.dumps(records, indent=2)+'\n')
        return name

    save('baseline5', baseline['groups'], dict(kind='unchanged_baseline'))
    if previous is not None:
        old = json.loads((previous/'candidates/stage1_affinity_0.02_corebatch_0.1/groups.json').read_text())
        save('previous6', old, dict(kind='unchanged_previous_candidate'))
    augmented = dict(data, edges=data['edges']+soft_edges(cores, cfg['core_soft_strength']))
    _RUN, _DATA, _AUGMENTED, _BASELINE, _CONFIG = run, data, augmented, baseline, cfg
    _WEIGHTS = [len(a) for a in data['atoms']]
    all_splits = {}
    local_stats = {}
    # Keep the serial release's seed/parent ordering for deterministic records.
    resource_parents = []
    for parent, vertices in enumerate(baseline['groups']):
        demand = base.demand_of(data, vertices)
        if any(demand[r] > base.SLR_CAPS[r] for r in ('DSP', 'BRAM18', 'URAM')):
            resource_parents.append(parent)
    resource = [('resource', parent, seed) for parent in resource_parents
                for seed in cfg['split_seeds']]
    pool = mp.get_context('fork').Pool(workers) if workers > 1 else None
    try:
        def results(items):
            return pool.imap(split_task, items, chunksize=1) if pool else map(split_task, items)

        for seed in cfg['split_seeds']:
            current = [('uniform', parent, seed)
                       for parent in range(len(baseline['groups']))]
            for (kind, parent, actual_seed), children, detail, _ in results(current):
                assert kind == 'uniform' and actual_seed == seed
                all_splits[parent, seed] = children
                local_stats[parent, seed] = detail
                if len(children) == 1:
                    continue
                n = sum(_WEIGHTS[a] for a in baseline['groups'][parent])
                groups = [g for i,g in enumerate(baseline['groups']) if i != parent]+children
                save(f'split_p{parent}_s{seed}', groups,
                     dict(kind='uniform_local_split', parent=f'P{parent:02d}', seed=seed,
                          proposal_cell_upper=math.ceil(cfg['split_max_parent_fraction']*n),
                          local_split=detail, maximum_local_split_fraction=detail['fraction']))
            combined = [g for p in range(len(baseline['groups']))
                        for g in all_splits[p, seed]]
            save(f'all_split_s{seed}', combined, dict(kind='combined_uniform_splits',
                 seed=seed, maximum_local_split_fraction=max(
                     v['fraction'] for (p,s),v in local_stats.items() if s == seed)))
        for (_, parent, seed), children, detail, _ in results(resource):
            demand = base.demand_of(data, baseline['groups'][parent])
            resource_name = max(('DSP', 'BRAM18', 'URAM'),
                                key=lambda r: demand[r]/base.SLR_CAPS[r])
            groups = [g for i,g in enumerate(baseline['groups']) if i != parent]+children
            save(f'resource_p{parent}_s{seed}', groups,
                 dict(kind='resource_driven_proposal', parent=f'P{parent:02d}',
                      resource=resource_name, seed=seed, local_split=detail,
                      maximum_local_split_fraction=detail['fraction']))
    except BaseException:
        if pool:
            pool.terminate()
        raise
    else:
        if pool:
            pool.close()
    finally:
        if pool:
            pool.join()
    (run/'generation_complete.json').write_text(
        json.dumps(dict(candidates=len(records), workers=workers), indent=2)+'\n')


if __name__ == '__main__':
    p=argparse.ArgumentParser()
    p.add_argument('run',type=Path)
    p.add_argument('previous',type=Path,nargs='?')
    p.add_argument('--workers',type=int,default=1)
    a=p.parse_args()
    main(a.run,a.previous,a.workers)
