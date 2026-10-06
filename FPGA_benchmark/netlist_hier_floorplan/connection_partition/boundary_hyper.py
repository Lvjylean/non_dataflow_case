"""Module-aware spatial hyperedges, not a static timing analysis graph.

Internal FF/LUT chains connect first DSP/RAM anchors. Cross-module segments
stop at sequential/macro boundaries and retain unanchored combinational modules.
The same retained anchors can also supply the directed spatial distance.
The immutable source graph still supplies cut, resources and path propagation.
"""
from collections import Counter, deque
import math

import numpy as np

from balanced_physical import atom_resource, expected_ranges
from static_regions import RESOURCES
from routed_density import resource_probabilities, region_cache_key

SCHEMA = 'boundary_spatial_v1'
HARD = frozenset(('DSP', 'BRAM18', 'URAM'))
TYPES = (*RESOURCES, 'COMB_CENTER')


def roles(data):
    """Keep dedicated atoms intact and treat hard macros as spatial anchors."""
    answer = []
    for a, demand in enumerate(data['atom_resources']):
        if any(demand.get(r, 0) for r in HARD):
            answer.append('hard')
        elif demand.get('FF', 0):
            refs = [data['cells'][c]['primitive'] for c in data['atoms'][a]]
            answer.append('ff' if all(r.startswith('FD') for r in refs) else 'boundary')
        elif demand.get('LUTMEM', 0):
            answer.append('boundary')
        else:
            answer.append('comb')
    return answer


class Frontier:
    """SCC-condensed reachability; reconvergent paths never multiply weights."""
    def __init__(self, adjacency, transparent, labels, same_module=False,
                 max_entries=10000000):
        n = len(adjacency)
        self.labels, self.transparent = labels, transparent
        graph = [[] for _ in range(n)]
        reverse = [[] for _ in range(n)]
        for a in range(n):
            if not transparent[a]:
                continue
            for b in adjacency[a]:
                if transparent[b] and (not same_module or labels[a] == labels[b]):
                    graph[a].append(b)
                    reverse[b].append(a)
        seen = bytearray(n)
        order = []
        for a in range(n):
            if not transparent[a] or seen[a]:
                continue
            seen[a] = 1
            stack = [(a, iter(graph[a]))]
            while stack:
                v, it = stack[-1]
                child = next(it, None)
                if child is None:
                    order.append(v)
                    stack.pop()
                elif not seen[child]:
                    seen[child] = 1
                    stack.append((child, iter(graph[child])))
        component = [-1] * n
        members = []
        for a in reversed(order):
            if component[a] >= 0:
                continue
            cid = len(members)
            component[a] = cid
            group, stack = [], [a]
            while stack:
                v = stack.pop()
                group.append(v)
                for b in reverse[v]:
                    if component[b] < 0:
                        component[b] = cid
                        stack.append(b)
            members.append(group)
        children = [set() for _ in members]
        parents = [[] for _ in members]
        targets = [set() for _ in members]
        masks = [0] * len(members)
        for cid, group in enumerate(members):
            for a in group:
                masks[cid] |= 1 << labels[a]
                for b in adjacency[a]:
                    if same_module and labels[a] != labels[b]:
                        continue
                    if transparent[b]:
                        if component[b] != cid:
                            children[cid].add(component[b])
                    else:
                        targets[cid].add(b)
                        masks[cid] |= 1 << labels[b]
        for cid, child_ids in enumerate(children):
            for child in child_ids:
                parents[child].append(cid)
        pending = [len(v) for v in children]
        queue = deque(c for c, degree in enumerate(pending) if not degree)
        entries = completed = 0
        while queue:
            cid = queue.popleft()
            for child in children[cid]:
                targets[cid].update(targets[child])
                masks[cid] |= masks[child]
                if len(targets[cid]) + entries > max_entries:
                    raise ValueError('Boundary frontier budget exceeded; no reachability was truncated.')
            targets[cid] = frozenset(targets[cid])
            entries += len(targets[cid])
            if entries > max_entries:
                raise ValueError('Boundary frontier budget exceeded; no reachability was truncated.')
            completed += 1
            for parent in parents[cid]:
                pending[parent] -= 1
                if not pending[parent]:
                    queue.append(parent)
        assert completed == len(members)
        self.component, self.targets, self.masks = component, targets, masks
        self.stats = dict(components=len(members), cyclic_components=sum(
            len(g) > 1 or any(a in graph[a] for a in g) for g in members),
            cached_terminal_entries=entries)

    def query(self, starts, module=None):
        targets, mask = set(), 0
        components = set()
        for a in starts:
            if module is not None and self.labels[a] != module:
                continue
            if self.transparent[a]:
                components.add(self.component[a])
            else:
                targets.add(a)
                mask |= 1 << self.labels[a]
        for cid in components:
            targets.update(self.targets[cid])
            mask |= self.masks[cid]
        return targets, mask


def lift(data, labels, module_count, max_entries=10000000, with_directed=False):
    """Emit one rooted hyperedge per source bit-net, with distinct anchor atoms.

Pin timing arcs/register settings are absent in the existing cache. Traversal
therefore describes conservative cell connectivity, not sensitizable paths.
"""
    required = ('atoms', 'atom_of', 'atom_resources', 'cells', 'nets')
    if any(k not in data for k in required):
        raise ValueError('Boundary model requires the original cell/net cache, not a quotient graph.')
    n = len(data['atoms'])
    if len(labels) != n or any(not 0 <= m < module_count for m in labels):
        raise ValueError('Invalid original-atom module labels.')
    role = roles(data)
    resource = [atom_resource(r) for r in data['atom_resources']]
    adjacency = [set() for _ in range(n)]
    roots = []
    stats = Counter()
    def atom(cell):
        return data['atom_of'][cell] if isinstance(cell, int) else -1
    for net_id, driver, sinks, weight in data['nets']:
        if not math.isfinite(weight) or weight < 0:
            raise ValueError('Invalid source-net weight.')
        a = atom(driver)
        target = tuple(sorted({atom(s) for s in sinks if atom(s) >= 0 and atom(s) != a}))
        stats['unknown_source_nets'] += int(a < 0)
        stats['unknown_sink_pins'] += sum(atom(s) < 0 for s in sinks)
        if a >= 0:
            adjacency[a].update(target)
        roots.append((net_id, a, target, weight / 4))
    normal = Frontier(adjacency, [r == 'comb' for r in role], labels, max_entries=max_entries)
    internal = Frontier(adjacency, [r in ('comb', 'ff') for r in role], labels,
                        same_module=True, max_entries=max_entries)
    # Preserve cross-module combinational islands that have no boundary source.
    reachable = bytearray(n)
    stack = [b for _, a, sinks, _ in roots if a < 0 or role[a] != 'comb'
             for b in sinks if role[b] == 'comb']
    while stack:
        a = stack.pop()
        if reachable[a]:
            continue
        reachable[a] = 1
        stack.extend(b for b in adjacency[a] if role[b] == 'comb' and not reachable[b])
    patterns = Counter()
    directed_weights, directed_counts = Counter(), Counter()
    for _, source, sinks, weight in roots:
        fallback = source >= 0 and role[source] == 'comb'
        if fallback and reachable[source]:
            continue
        ends, mask = normal.query(sinks)
        if source >= 0:
            mask |= 1 << labels[source]
        anchors = set(ends)
        if source >= 0 and role[source] != 'comb':
            anchors.add(source)
        cross = bool(mask and mask & (mask - 1))
        proxies = set()
        if cross:
            anchored_modules = {labels[a] for a in anchors}
            proxies = {m for m in range(module_count) if mask & (1 << m)
                       and m not in anchored_modules}
            stats['cross_source_nets'] += 1
            stats['unrooted_comb_fallback_nets'] += int(fallback)
        elif source >= 0 and role[source] == 'hard':
            ends, _ = internal.query(sinks, module=labels[source])
            anchors = {source} | {a for a in ends if role[a] == 'hard'}
            if len(anchors) < 2:
                stats['ignored_internal_source_nets'] += 1
                continue
            stats['internal_hard_source_nets'] += 1
        else:
            stats['ignored_internal_source_nets'] += 1
            continue
        slots = Counter(labels[a] * len(TYPES) + TYPES.index(resource[a]) for a in anchors)
        for m in proxies:
            slots[m * len(TYPES) + len(RESOURCES)] = 1
        if sum(slots.values()) < 2:
            stats['one_position_source_nets'] += 1
            continue
        patterns[tuple(sorted(slots.items()))] += weight
        stats['retained_source_nets'] += 1
        stats['comb_module_proxy_occurrences'] += len(proxies)
        if with_directed:
            if source < 0:
                stats['directed_unknown_source_roots'] += 1
                continue
            # A spatial source star, not a replacement for the original timing
            # graph. Distinct receivers survive; reconvergent routes do not
            # multiply them. A pure-combinational fallback uses a mean source.
            root = labels[source] * len(TYPES) + TYPES.index(
                'COMB_CENTER' if fallback else resource[source])
            targets = Counter(labels[a] * len(TYPES) + TYPES.index(resource[a])
                              for a in anchors if a != source)
            for m in proxies:
                proxy = m * len(TYPES) + len(RESOURCES)
                if proxy != root:
                    targets[proxy] += 1
            for target, count in targets.items():
                directed_weights[root, target] += weight * count
                directed_counts[root, target] += count
    audit = dict(stats, schema=SCHEMA, ordinary_frontier=normal.stats,
                 internal_frontier=internal.stats, pattern_count=len(patterns),
                 effective_weight=sum(patterns.values()),
                 source_net_weight=sum(w / 4 for _, _, _, w in data['nets']),
                 path_multiplicity='Distinct endpoints per source bit-net; no path-count expansion.',
                 unknown_positions='Unknown ports/infrastructure are counted and have no invented coordinates.',
                 semantics='Cell-connectivity spatial proxy; internal FF traversal may cross cycles.',
                 same_atom_geometry='Dedicated atoms stay intact; their internal geometry is not expanded.')
    if with_directed:
        directed = dict(schema='boundary_directed_v1', module_count=module_count,
            resource_types=list(TYPES), pairs=[dict(source=a, sink=b, weight=w,
                endpoints=directed_counts[a,b]) for (a,b),w in sorted(directed_weights.items())],
            audit=dict(audit, directed_endpoint_branches=sum(directed_counts.values()),
                directed_effective_weight=sum(directed_weights.values()),
                semantics='Source bit-net stars to distinct retained anchors and mean combinational proxies; not raw sink-pin or timing-path counts.'))
        return patterns, audit, directed
    return patterns, audit


class BoundaryNetModel:
    schema = SCHEMA
    resource_types = TYPES
    def __init__(self, data, labels, module_count, device, max_entries=10000000):
        self.device, self.modules = device, module_count
        self.dimensions = [max(d[k] for d in device.values()) for k in ('x', 'y', 'slr')]
        patterns, self.audit, self.directed_data = lift(
            data, labels, module_count, max_entries, with_directed=True)
        self.patterns = list(patterns)
        self.weights = np.asarray(list(patterns.values()), dtype=float)
        self.counts = np.zeros((len(patterns), module_count * len(TYPES)))
        self.pattern_modules = []
        for i, pattern in enumerate(self.patterns):
            for slot, count in pattern:
                self.counts[i, slot] = count
            self.pattern_modules.append({slot // len(TYPES) for slot, _ in pattern})
        self.cross = np.asarray([len(ms) > 1 for ms in self.pattern_modules], dtype=bool)
        self.internal = {m: np.asarray([i for i, ms in enumerate(self.pattern_modules) if ms == {m}], dtype=int)
                         for m in range(module_count)}
        self._cache = {}

    def distributions(self, region):
        key = region_cache_key(region)
        if key not in self._cache:
            profiles = []
            for resource in RESOURCES:
                probabilities = resource_probabilities(region, self.device, resource)
                profiles.append([(tuple(self.device[c][a] for a in ('x', 'y', 'slr')), p)
                                 for c, p in probabilities.items() if p])
            # One deterministic mean position per unanchored module, not one
            # independent random LUT location for every intermediate cell.
            lut = profiles[RESOURCES.index('LUT')]
            center = tuple(sum(point[a] * p for point, p in lut) for a in range(3))
            profiles.append([(center, 1.)] if lut else [])
            self._cache[key] = profiles
        return self._cache[key]

    def _ranges(self, profiles, counts):
        result = np.zeros((len(counts), 3))
        active = np.flatnonzero(np.any(counts > 0, axis=0))
        if any(not profiles[s] for s in active):
            raise ValueError('A retained anchor/proxy has no resource capacity in its region.')
        for axis in range(3):
            coordinates = sorted({point[axis] for s in active for point, _ in profiles[s]})
            if len(coordinates) < 2:
                continue
            cuts = coordinates[:-1]
            cdf = np.asarray([[sum(p for point, p in profiles[s] if point[axis] <= t)
                               for t in cuts] for s in active])
            result[:, axis] = expected_ranges(counts[:, active], cdf) @ np.diff(coordinates)
        return result

    def components(self, chosen, slr_weight=4):
        profiles = [p for m in range(self.modules) for p in self.distributions(chosen[f'P{m:02d}'])]
        ranges = self._ranges(profiles, self.counts)
        spans = self.weights @ ranges
        per_edge = ranges @ np.array([1., 1., slr_weight])
        return dict(x_span=float(spans[0]), y_span=float(spans[1]), slr_span=float(spans[2]),
                    internal_span_cost=float(self.weights[~self.cross] @ per_edge[~self.cross]),
                    boundary_span_cost=float(self.weights[self.cross] @ per_edge[self.cross]),
                    physical_cost=float(self.weights @ per_edge))

    def internal_region_cost(self, m, region, slr_weight=4):
        ids = self.internal[m]
        if not len(ids):
            return 0.
        lo, hi = m * len(TYPES), (m + 1) * len(TYPES)
        ranges = self._ranges(self.distributions(region), self.counts[ids, lo:hi])
        return float(self.weights[ids] @ ranges @ np.array([1., 1., slr_weight]))


def independent_spans(model, chosen):
    """Scalar integration for verification; does not call optimizer scoring."""
    profiles = {}
    for m in range(model.modules):
        region = chosen[f'P{m:02d}']
        if region.get('density_profile'):
            raise ValueError('Boundary verifier requires the declared capacity-only profile.')
        for ri, resource in enumerate(RESOURCES):
            entries = [(tuple(model.device[c][a] for a in ('x', 'y', 'slr')),
                        model.device[c]['resources'][resource]) for c in region['crs']]
            total = sum(n for _, n in entries)
            profiles[m * len(TYPES) + ri] = [(point, n / total) for point, n in entries if n]
        lut = profiles[m * len(TYPES) + RESOURCES.index('LUT')]
        profiles[m * len(TYPES) + len(RESOURCES)] = [(
            tuple(sum(point[a] * p for point, p in lut) for a in range(3)), 1.)] if lut else []
    spans = dict(x=0., y=0., slr=0.)
    for pattern, weight in zip(model.patterns, model.weights):
        for axis, name in enumerate(spans):
            support = sorted({point[axis] for s, _ in pattern for point, _ in profiles[s]})
            for low, high in zip(support, support[1:]):
                left = right = 1.
                for s, count in pattern:
                    p = sum(mass for point, mass in profiles[s] if point[axis] <= low)
                    left *= p ** count
                    right *= (1 - p) ** count
                spans[name] += float(weight) * (high - low) * max(0., 1 - left - right)
    return spans
