"""Staged, cache-only experiments; the original partition entry point is unchanged."""
import argparse
import csv
import gzip
import hashlib
import json
import math
import pickle
import random
from collections import Counter, defaultdict
from pathlib import Path

import partition as base


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(4 << 20), b''):
            h.update(block)
    return h.hexdigest()


def labels_for(data, groups):
    labels = [-1] * len(data['atoms'])
    for m, group in enumerate(groups):
        assert group
        for a in group:
            assert labels[a] == -1
            labels[a] = m
    assert all(labels[a] >= 0 for a in data['active_atoms'])
    assert sum(len(g) for g in groups) == len(data['active_atoms'])
    return labels


def objective(edges, labels):
    km1 = cut = 0
    for edge, weight in edges:
        n = len({labels[a] for a in edge})
        km1 += weight * (n - 1)
        cut += weight * (n > 1)
    return km1 / 4, cut / 4


def merge_statistics(data, groups):
    labels = labels_for(data, groups)
    volume = Counter(); shared = Counter()
    for edge, weight in data['edges']:
        touched = sorted({labels[a] for a in edge})
        for m in touched:
            volume[m] += weight
        for i, a in enumerate(touched):
            for b in touched[i + 1:]:
                shared[a, b] += weight
    return volume, shared


def selective_merge(data, groups, threshold, cell_cap=150000):
    """Require relative affinity, not merely a positive cut reduction."""
    groups = [list(g) for g in groups]
    log = []
    while True:
        volume, shared = merge_statistics(data, groups)
        choice = None
        for (a, b), gain in sorted(shared.items(), key=lambda p: (-p[1], p[0])):
            affinity = gain / min(volume[a], volume[b])
            if affinity >= threshold and base.fits(data, groups[a] + groups[b], cell_cap):
                choice = a, b, gain, affinity
                break
        if choice is None:
            break
        a, b, gain, affinity = choice
        log.append(dict(gain=gain / 4, affinity=affinity,
                        cells=[sum(len(data['atoms'][v]) for v in groups[m]) for m in (a, b)]))
        groups[a].extend(groups[b]); del groups[b]
    groups.sort(key=lambda g: (-sum(len(data['atoms'][a]) for a in g), min(g)))
    volume, shared = merge_statistics(data, groups)
    rejected = [dict(pair=[a, b], gain=gain / 4,
                     affinity=gain / min(volume[a], volume[b]))
                for (a, b), gain in shared.items()
                if base.fits(data, groups[a] + groups[b], cell_cap)]
    return groups, dict(threshold=threshold, merges=log, capacity_safe_remaining_pairs=rejected)


def logical_cores(data, minimum=32, maximum=30000, cohesion=.5):
    """Use coherent exact parent groups; never make a giant top hierarchy atomic."""
    by_hierarchy = defaultdict(list)
    hierarchy_of = [None] * len(data['atoms'])
    for a, members in enumerate(data['atoms']):
        hs = {data['cells'][c]['original_hierarchy'] for c in members}
        if len(hs) == 1 and 'TOP' not in hs:
            h = next(iter(hs)); by_hierarchy[h].append(a); hierarchy_of[a] = h
    candidates = {h: group for h, group in by_hierarchy.items()
                  if minimum <= sum(len(data['atoms'][a]) for a in group) <= maximum}
    volume = Counter(); internal = Counter()
    for edge, weight in data['edges']:
        hs = {hierarchy_of[a] for a in edge}
        for h in hs:
            if h in candidates:
                volume[h] += weight
        if len(hs) == 1:
            h = next(iter(hs))
            if h in candidates:
                internal[h] += weight
    cores = []
    for h, group in sorted(candidates.items()):
        if internal[h] and internal[h] / volume[h] >= cohesion:
            cores.append(dict(hierarchy=h, atoms=group,
                              cells=sum(len(data['atoms'][a]) for a in group),
                              internal_weight=internal[h], cohesion=internal[h] / volume[h]))
    return cores


def core_metrics(data, labels, cores):
    fragments = minority = fragmented = 0
    for core in cores:
        counts = Counter()
        for a in core['atoms']:
            counts[labels[a]] += len(data['atoms'][a])
        fragments += len(counts) - 1
        fragmented += len(counts) > 1
        minority += sum(counts.values()) - max(counts.values())
    return dict(cores=len(cores), fragmented_cores=fragmented,
                extra_core_fragments=fragments, core_minority_cells=minority)


def soft_edges(cores, strength):
    if not strength:
        return []
    return [(tuple(c['atoms']), max(1, round(strength * c['internal_weight'])))
            for c in cores if len(c['atoms']) > 1]


def move_gain(counts, source, target, weight):
    return weight * ((counts[source] == 1) - (counts.get(target, 0) == 0))


def boundary_refine(data, groups, cores, strength=.02, rounds=2,
                    cell_cap=150000, real_budget_fraction=.02, seed=0):
    """Positive-gain boundary moves with exact incremental hyperedge counts."""
    labels = labels_for(data, groups)
    original = list(labels)
    real_count = len(data['edges'])
    edges = data['edges'] + soft_edges(cores, strength)
    incident = [[] for _ in data['atoms']]
    counts = []
    for e, (pins, weight) in enumerate(edges):
        counts.append(Counter(labels[a] for a in pins))
        for a in pins:
            incident[a].append(e)
    sizes = [sum(len(data['atoms'][a]) for a in g) for g in groups]
    demands = [base.demand_of(data, g) for g in groups]
    real_start = objective(data['edges'], labels)[0] * 4
    current_real = real_start
    original_total = objective(edges, labels)[0] * 4
    history = []
    rng = random.Random(seed)
    for iteration in range(rounds):
        order = list(data['active_atoms']); rng.shuffle(order)
        moved = moved_top = 0
        for a in order:
            source = labels[a]
            targets = set()
            for e in incident[a]:
                if len(counts[e]) > 1:
                    targets.update(counts[e])
            targets.discard(source)
            n = len(data['atoms'][a])
            if not targets or sizes[source] == n:
                continue
            demand = data['atom_resources'][a]
            best = None
            for target in sorted(targets):
                if sizes[target] + n > cell_cap or any(
                        demands[target][r] + demand.get(r, 0) > cap for r, cap in base.CAPS.items()):
                    continue
                gain = real_gain = 0
                for e in incident[a]:
                    delta = move_gain(counts[e], source, target, edges[e][1])
                    gain += delta
                    if e < real_count:
                        real_gain += delta
                if gain <= 0 or current_real - real_gain > real_start * (1 + real_budget_fraction):
                    continue
                candidate = (gain, real_gain, -target)
                if best is None or candidate > best:
                    best = candidate
            if best is None:
                continue
            _, real_gain, negative_target = best
            target = -negative_target
            for e in incident[a]:
                counts[e][source] -= 1
                if counts[e][source] == 0:
                    del counts[e][source]
                counts[e][target] += 1
            labels[a] = target; sizes[source] -= n; sizes[target] += n
            demands[source].subtract(demand); demands[target].update(demand)
            current_real -= real_gain
            moved += n
            moved_top += sum(data['cells'][c]['original_hierarchy'] == 'TOP' for c in data['atoms'][a])
        exact_real = objective(data['edges'], labels)[0] * 4
        assert exact_real == current_real
        total = objective(edges, labels)[0] * 4
        assert total <= original_total
        entry = dict(iteration=iteration, moved_cells=moved, moved_top_cells=moved_top,
                     real_km1=current_real / 4, augmented_km1=total / 4)
        history.append(entry); base.log('boundary_pass', strength=strength, **entry)
        if not moved:
            break
    refined = [[] for _ in groups]
    for a in data['active_atoms']:
        refined[labels[a]].append(a)
    return refined, dict(strength=strength, history=history,
        final_changed_cells=sum(len(data['atoms'][a]) for a in data['active_atoms'] if labels[a] != original[a]),
        final_changed_top_cells=sum(data['cells'][c]['original_hierarchy'] == 'TOP'
            for a in data['active_atoms'] if labels[a] != original[a] for c in data['atoms'][a]))


def save_candidate(run, name, data, groups, cores, baseline_labels, extra=None):
    labels = labels_for(data, groups)
    km1, cut = objective(data['edges'], labels)
    result = dict(groups=groups, membership=labels, weighted_km1=km1, weighted_cut=cut)
    owner, modules, pairs, ports, metrics = base.summaries(data, result)
    for m, group in zip(modules, groups):
        parents = Counter()
        for a in group:
            parents[f'P{baseline_labels[a]:02d}'] += len(data['atoms'][a])
        m['baseline_parent_cells'] = dict(parents)
    for resource in base.RESOURCES:
        assert sum(m[resource] for m in modules) == data['totals'].get(resource, 0)
    summary = dict(name=name, modules=modules, metrics={**metrics, **core_metrics(data, labels, cores),
        'module_count':len(groups), 'near_cell_cap_count':sum(m['cells'] >= 135000 for m in modules),
        'min_cells':min(m['cells'] for m in modules), 'max_cells':max(m['cells'] for m in modules)},
        connections=[dict(source=a,sink=b,**dict(p)) for (a,b),p in sorted(pairs.items())],
        provenance=extra or {}, inventory=data['stats'], total_resources=data['totals'])
    out = run/'candidates'/name; out.mkdir(parents=True)
    (out/'groups.json').write_text(json.dumps(groups)+'\n')
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    base.log('candidate', name=name, **summary['metrics'])
    return summary


def load_context(run):
    with (run/'graph.pkl').open('rb') as f:
        data = pickle.load(f)
    reference = json.loads((run/'baseline/final/modules.json').read_text())
    original = json.loads((run/f"baseline/result_k{reference['initial_k']}_s{reference['selected_seed']}/partition.json").read_text())
    baseline = base.normalize_multislr(data, original)
    assert objective(data['edges'],baseline['membership'])[0] == reference['metrics']['weighted_km1']
    assert digest(reference['input_dcp']) == reference['input_sha256']
    return data, original, baseline, reference


def stage12(run):
    data, original, baseline, reference = load_context(run)
    cores = logical_cores(data)
    (run/'cores.json').write_text(json.dumps(cores)+'\n')
    base.log('cores', count=len(cores), cells=sum(c['cells'] for c in cores))
    summaries = [save_candidate(run,'baseline',data,baseline['groups'],cores,baseline['membership'])]
    selected = None
    for threshold in (.005,.01,.02):
        groups, detail = selective_merge(data, original['groups'], threshold)
        name = f'stage1_affinity_{threshold:g}'
        summaries.append(save_candidate(run,name,data,groups,cores,baseline['membership'],detail))
        if threshold == .01:
            selected = groups
    for strength in (0,.02):
        groups, detail = boundary_refine(data,selected,cores,strength=strength)
        name = 'stage2_real_only' if not strength else 'stage2_logical'
        summaries.append(save_candidate(run,name,data,groups,cores,baseline['membership'],detail))
    (run/'stage12_summary.json').write_text(json.dumps(summaries,indent=2)+'\n')
    (run/'binding.json').write_text(json.dumps(dict(input_dcp=reference['input_dcp'],
        input_sha256=reference['input_sha256'], graph_sha256=digest(run/'graph.pkl'),
        baseline_commit='8bcc512bf67cd0caa8ff62886bdc8a4e8a60c71e'),indent=2)+'\n')


def split(run, pieces, seed):
    data, original, baseline, reference = load_context(run)
    cores = json.loads((run/'cores.json').read_text())
    groups = json.loads((run/'candidates/stage2_logical/groups.json').read_text())
    # Identify the resource-heavy logical parent from demand, not an instance name.
    heavy_parent = max(range(len(baseline['groups'])),
        key=lambda i:base.demand_of(data,baseline['groups'][i])['URAM'])
    affected = [i for i,g in enumerate(groups)
                if sum(len(data['atoms'][a]) for a in g if baseline['membership'][a] == heavy_parent)
                > .5 * sum(len(data['atoms'][a]) for a in g)]
    vertices = [a for i in affected for a in groups[i]]
    demand = base.demand_of(data,vertices)
    resource = max(('URAM','DSP','BRAM18'),key=lambda r:demand[r]/base.SLR_CAPS[r])
    total_cells = sum(len(data['atoms'][a]) for a in vertices)
    upper = min(base.SLR_CAPS[resource], math.ceil(1.25*demand[resource]/pieces))
    scale = total_cells + 1
    weights = {a:data['atom_resources'][a].get(resource,0)*scale+len(data['atoms'][a]) for a in vertices}
    target = upper*scale+total_cells
    augmented = dict(data, edges=data['edges']+soft_edges(cores,.02))
    tag = f'local_k{pieces}_s{seed}'
    subgroups = base.run_kahypar(run,augmented,vertices,pieces,[target]*pieces,weights,tag,seed)
    assert len(subgroups) == pieces
    for g in subgroups:
        assert base.demand_of(data,g)[resource] <= upper
        assert base.fits(data,g,150000)
    final = [g for i,g in enumerate(groups) if i not in affected] + subgroups
    save_candidate(run, f'stage3_k{pieces}_s{seed}', data, final, cores, baseline['membership'],
        dict(logical_parent=f'P{heavy_parent:02d}',replaced_stage2_groups=affected,
             resource=resource,resource_upper=upper,local_k=pieces,seed=seed,
             real_net_objective_separate_from_soft_hierarchy=True))


def deliver(run, name):
    data, original, baseline, reference = load_context(run)
    folder = run/'candidates'/name
    summary = json.loads((folder/'summary.json').read_text())
    groups = json.loads((folder/'groups.json').read_text())
    labels = labels_for(data,groups)
    result = dict(groups=groups,membership=labels,
                  weighted_km1=summary['metrics']['weighted_km1'],weighted_cut=summary['metrics']['weighted_cut'])
    owner, modules, pairs, ports, metrics = base.summaries(data,result)
    out = run/'selected';out.mkdir()
    with gzip.open(out/'leaf_cells.tsv.gz','wt') as f:
        fields = ['cell_id','cell_name','primitive','original_hierarchy','module_id',*base.RESOURCES]
        writer = csv.DictWriter(f,fieldnames=fields,delimiter='\t');writer.writeheader()
        for row,mid in zip(data['cells'],owner):
            demand = base.resources(row['primitive'])
            writer.writerow(dict(row,module_id=mid,**{r:demand.get(r,0) for r in base.RESOURCES}))
    base.write_table(out/'module_resources.tsv',summary['modules'],
        ['module_id','cells',*base.RESOURCES,'top_direct_cells','floorplan_eligible'])
    base.write_table(out/'module_connections.tsv',summary['connections'],
        ['source','sink','nets','sink_pin_connections','weighted_nets','data_nets','control_nets'])
    (out/'modules.json').write_text(json.dumps(dict(summary,input_dcp=reference['input_dcp'],
        input_sha256=reference['input_sha256'], infrastructure=reference['infrastructure'],
        cell_cap=150000,initial_k=8,selected_candidate=name),indent=2)+'\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action',choices=['stage12','split','deliver'])
    parser.add_argument('run',type=Path)
    parser.add_argument('--pieces',type=int,default=2)
    parser.add_argument('--seed',type=int,default=0)
    parser.add_argument('--candidate')
    args = parser.parse_args()
    if args.action == 'stage12': stage12(args.run)
    elif args.action == 'split': split(args.run,args.pieces,args.seed)
    else: deliver(args.run,args.candidate)
