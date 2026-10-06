"""Bounded group moves on original nets, with exact km1 and pin-cut deltas."""
import time
from array import array
from collections import Counter, defaultdict

import partition as base
from structure_frontend import Union, cut_metrics, label_groups, operator_loss


def components(data, labels, units=()):
    union = Union(len(labels))
    for _, d, sinks, _ in data['nets']:
        if not isinstance(d, int):
            continue
        a = data['atom_of'][d]
        if a < 0:
            continue
        for s in sinks:
            b = data['atom_of'][s] if isinstance(s, int) else -1
            if b >= 0 and labels[a] == labels[b]:
                union.join(a, b)
    # The optional closure makes already complete operators indivisible only
    # during this local round. Diagnostics omit this artificial closure.
    for unit in units:
        aa = unit['atoms']
        if len({labels[a] for a in aa}) == 1:
            for a in aa[1:]:
                union.join(aa[0], a)
    grouped = defaultdict(lambda: defaultdict(list))
    for a, m in enumerate(labels):
        grouped[m][union.find(a)].append(a)
    return {m: sorted(parts.values(), key=lambda aa: (-sum(len(data['atoms'][a]) for a in aa), min(aa)))
            for m, parts in grouped.items()}


def connectivity_metrics(data, labels):
    output = []
    for m, parts in sorted(components(data, labels).items()):
        sizes = [sum(len(data['atoms'][a]) for a in aa) for aa in parts]
        output.append(dict(module=m, cells=sum(sizes), components=len(sizes),
                           largest_component_cells=max(sizes),
                           largest_component_fraction=max(sizes)/sum(sizes),
                           component_sizes=sizes))
    return output


class OriginalIndex:
    def __init__(self, data, groups, units, resource_fits=None):
        self.data = data
        self.resource_fits = resource_fits
        self.labels = label_groups(groups, len(data['atoms']))
        self.units = units
        self.unit_of = {}
        for i, unit in enumerate(units):
            for a in unit['atoms']:
                if a in self.unit_of:
                    raise ValueError('Overlapping units')
                self.unit_of[a] = i
        self.edge_incident = [array('I') for _ in self.labels]
        self.net_incident = [array('I') for _ in self.labels]
        self.demands = defaultdict(Counter)
        self.module_volumes = Counter()
        for a, m in enumerate(self.labels):
            self.demands[m].update(data['atom_resources'][a])
        for i, (aa, weight) in enumerate(data['edges']):
            for a in aa:
                self.edge_incident[a].append(i)
            for m in {self.labels[a] for a in aa}:
                self.module_volumes[m] += weight
        for i, (_, d, ss, _) in enumerate(data['nets']):
            aa = {data['atom_of'][c] for c in (d, *ss)
                  if isinstance(c, int) and data['atom_of'][c] >= 0}
            for a in aa:
                self.net_incident[a].append(i)

    def branch_cost(self, net, moved=frozenset(), target=-1):
        _, d, ss, w = net
        if not isinstance(d, int) or self.data['atom_of'][d] < 0:
            return 0, 0
        a = self.data['atom_of'][d]
        md = target if a in moved else self.labels[a]
        pins = 0
        for s in ss:
            b = self.data['atom_of'][s] if isinstance(s, int) else -1
            if b >= 0:
                pins += md != (target if b in moved else self.labels[b])
        return pins*w, pins

    def total(self):
        values = [self.branch_cost(net) for net in self.data['nets']]
        return dict(**cut_metrics(self.data['edges'], self.labels),
                    weighted_cross_pins=sum(v[0] for v in values)/4,
                    cross_pins=sum(v[1] for v in values),
                    **operator_loss(self.data, self.labels, self.units))

    def proposal(self, atoms, target):
        moved = {a for a in atoms if self.labels[a] != target}
        if not moved:
            return None
        addition = Counter()
        for a in moved:
            addition.update(self.data['atom_resources'][a])
        combined = self.demands[target]+addition
        if (not self.resource_fits(combined) if self.resource_fits else
                any(combined[r] > cap for r, cap in base.CAPS.items())):
            return None
        loss_delta = 0
        for u in {self.unit_of[a] for a in moved if a in self.unit_of}:
            old, new = Counter(), Counter()
            for a in self.units[u]['atoms']:
                n = len(self.data['atoms'][a])
                old[self.labels[a]] += n
                new[target if a in moved else self.labels[a]] += n
            if len(old) == 1 and len(new) > 1:
                return None
            loss_delta += max(old.values())-max(new.values())
        if loss_delta > 0:
            return None
        edges = {e for a in moved for e in self.edge_incident[a]}
        piece_volume = sum(self.data['edges'][e][1] for e in edges)
        shared = sum(self.data['edges'][e][1] for e in edges
                     if any(self.labels[a] == target for a in self.data['edges'][e][0]))
        denominator = min(piece_volume, self.module_volumes[target])
        affinity = shared / denominator if denominator else 0.
        delta_cut4 = delta_km4 = 0
        for e in edges:
            aa, w = self.data['edges'][e]
            old = len({self.labels[a] for a in aa})
            new = len({target if a in moved else self.labels[a] for a in aa})
            delta_km4 += w*(new-old)
            delta_cut4 += w*((new > 1)-(old > 1))
        nets = {i for a in moved for i in self.net_incident[a]}
        delta_b4 = delta_pins = 0
        neighbors = set()
        for i in nets:
            net = self.data['nets'][i]
            before = self.branch_cost(net)
            after = self.branch_cost(net, moved, target)
            delta_b4 += after[0]-before[0]
            delta_pins += after[1]-before[1]
            for c in (net[1], *net[2]):
                if isinstance(c, int) and self.data['atom_of'][c] >= 0:
                    neighbors.add(self.labels[self.data['atom_of'][c]])
        return dict(atoms=sorted(moved), target=target, cells=sum(len(self.data['atoms'][a]) for a in moved),
                    delta_km1=delta_km4/4, delta_cut=delta_cut4/4,
                    delta_weighted_cross_pins=delta_b4/4, delta_cross_pins=delta_pins,
                    delta_operator_minority=loss_delta, neighbors=sorted(neighbors),
                    merge_affinity=affinity)

    def destinations(self, atoms):
        nets = {i for a in atoms for i in self.net_incident[a]}
        affinity = Counter()
        aset = set(atoms)
        for i in nets:
            _, d, ss, w = self.data['nets'][i]
            a = self.data['atom_of'][d] if isinstance(d, int) else -1
            if a < 0:
                continue
            for s in ss:
                b = self.data['atom_of'][s] if isinstance(s, int) else -1
                if b < 0:
                    continue
                if a in aset and b not in aset:
                    affinity[self.labels[b]] += w
                if b in aset and a not in aset:
                    affinity[self.labels[a]] += w
        return [m for m, _ in sorted(affinity.items(), key=lambda x: (-x[1], x[0]))]

    def apply(self, proposal):
        target = proposal['target']
        edges = {e for a in proposal['atoms'] for e in self.edge_incident[a]}
        for e in edges:
            aa, weight = self.data['edges'][e]
            for m in {self.labels[a] for a in aa}:
                self.module_volumes[m] -= weight
        for a in proposal['atoms']:
            old = self.labels[a]
            self.demands[old].subtract(self.data['atom_resources'][a])
            self.demands[target].update(self.data['atom_resources'][a])
            self.labels[a] = target
        for e in edges:
            aa, weight = self.data['edges'][e]
            for m in {self.labels[a] for a in aa}:
                self.module_volumes[m] += weight


def refine(data, groups, units, cfg, resource_fits=None):
    from joint_units import require_intact
    if cfg.get('require_intact_units'):
        require_intact(label_groups(groups,len(data['atoms'])),units,'local refinement input')
    t0 = time.monotonic()
    index = OriginalIndex(data, groups, units, resource_fits)
    before = index.total()
    indexed_seconds = time.monotonic()-t0
    started = time.monotonic()
    history = []
    evaluations = 0
    timed_out = False
    affinity_rejections = 0
    affinity_threshold = float(cfg.get('component_affinity_threshold', 0.))
    if not 0. <= affinity_threshold <= 1.:
        raise ValueError('Component affinity threshold must be between zero and one.')

    def process(atoms, kind, key):
        nonlocal evaluations, timed_out, affinity_rejections
        best = None
        for target in index.destinations(atoms):
            if time.monotonic()-started >= cfg['local_search_seconds']:
                timed_out = True
                break
            p = index.proposal(atoms, target)
            evaluations += 1
            if p is None or p['delta_km1'] > 0 or p['delta_weighted_cross_pins'] > 0:
                continue
            if kind == 'loose_component_move' and p['merge_affinity'] < affinity_threshold:
                affinity_rejections += 1
                continue
            if not (p['delta_km1'] < 0 or p['delta_weighted_cross_pins'] < 0 or p['delta_operator_minority'] < 0):
                continue
            score = (p['delta_operator_minority'], p['delta_km1'], p['delta_weighted_cross_pins'], p['cells'], target)
            if best is None or score < best[0]:
                best = score, p
        if best:
            p = best[1]
            index.apply(p)
            history.append(dict(kind=kind, key=key, **{k:v for k,v in p.items() if k != 'atoms'}))

    for unit in units:
        if len({index.labels[a] for a in unit['atoms']}) > 1:
            process(unit['atoms'], 'operator_repair', unit['hierarchy'])
        if timed_out or len(history) >= cfg['local_max_moves']:
            break
    if cfg.get('move_components', True) and not timed_out and len(history) < cfg['local_max_moves']:
        parts = components(data, index.labels, units)
        queue = []
        for m, groups_m in parts.items():
            sizes = [sum(len(data['atoms'][a]) for a in aa) for aa in groups_m]
            if max(sizes)/sum(sizes) < cfg['loose_module_connected_fraction']:
                queue.extend((m, aa) for aa in groups_m)
        for m, aa in sorted(queue, key=lambda p:(p[0], -sum(len(data['atoms'][a]) for a in p[1]), min(p[1]))):
            process(aa, 'loose_component_move', f'original_module_{m}_atom_{min(aa)}')
            if timed_out or len(history) >= cfg['local_max_moves']:
                break
    searched_seconds = time.monotonic()-started
    after = index.total()
    assert after['weighted_km1'] <= before['weighted_km1']
    assert after['weighted_cross_pins'] <= before['weighted_cross_pins']
    assert after['operator_minority_cells'] <= before['operator_minority_cells']
    out = defaultdict(list)
    for a, m in enumerate(index.labels):
        out[m].append(a)
    retained = sorted(out)
    result = [out[m] for m in retained]
    final_labels = label_groups(result, len(data['atoms']))
    if cfg.get('require_intact_units'):
        require_intact(final_labels,units,'local refinement output')
    return result, dict(before=before, after=after, history=history, evaluations=evaluations,
        component_affinity_threshold=affinity_threshold, affinity_rejections=affinity_rejections,
        time_budget_reached=timed_out, indexing_seconds=indexed_seconds, search_seconds=searched_seconds,
        total_seconds=time.monotonic()-t0, old_to_new_modules={str(m):i for i,m in enumerate(retained)},
        connectivity=connectivity_metrics(data, final_labels),
        scope='No physical optimization. Resource capacities screened; final CR feasibility must be evaluated separately.')
