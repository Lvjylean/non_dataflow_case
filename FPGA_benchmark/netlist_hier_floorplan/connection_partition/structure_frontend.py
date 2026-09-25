"""Optional, reversible operator contraction on an immutable physical-atom graph."""
import re
from collections import Counter, defaultdict

DEFAULT_PATTERN = r'^(?:d(?:mul|sub|add|div|cmp|sqrt)|u(?:div|rem)|s(?:div|rem)|mul)_'


class Union:
    def __init__(self, n):
        self.parent = list(range(n))
        self.size = [1] * n

    def find(self, a):
        while self.parent[a] != a:
            self.parent[a] = self.parent[self.parent[a]]
            a = self.parent[a]
        return a

    def join(self, a, b):
        a, b = self.find(a), self.find(b)
        if a == b:
            return
        if self.size[a] < self.size[b]:
            a, b = b, a
        self.parent[b] = a
        self.size[a] += self.size[b]


def label_groups(groups, n):
    labels = [-1] * n
    for m, group in enumerate(groups):
        if not group:
            raise ValueError('Empty module')
        for a in group:
            if not 0 <= a < n or labels[a] != -1:
                raise ValueError('Duplicate or invalid atom')
            labels[a] = m
    if -1 in labels:
        raise ValueError('Missing atom')
    return labels


def cut_metrics(edges, labels):
    cut = km1 = 0
    for aa, w in edges:
        n = len({labels[a] for a in aa})
        cut += w * (n > 1)
        km1 += w * (n - 1)
    return dict(weighted_cut=cut / 4, weighted_km1=km1 / 4)


def operator_loss(data, labels, units):
    minority = split = 0
    for unit in units:
        counts = Counter()
        for a in unit['atoms']:
            counts[labels[a]] += len(data['atoms'][a])
        split += len(counts) > 1
        minority += sum(counts.values()) - max(counts.values())
    return dict(operator_count=len(units), split_operators=split, operator_minority_cells=minority)


def discover(data, cfg):
    """Naming proposes boundaries; original connectivity validates each proposal."""
    pattern = re.compile(cfg.get('operator_pattern', DEFAULT_PATTERN))
    proposals = {}
    cell_unit = [-1] * len(data['cells'])
    paths = []
    for c, row in enumerate(data['cells']):
        if data['atom_of'][c] < 0:
            continue
        parts = row['cell_name'].split('/')
        for k, part in enumerate(parts[:-1]):
            if pattern.match(part):
                path = '/'.join(parts[:k + 1])
                if path not in proposals:
                    proposals[path] = len(paths)
                    paths.append(path)
                cell_unit[c] = proposals[path]
                break
    atom_unit = [-1] * len(data['atoms'])
    members = defaultdict(list)
    rejected = set()
    for a, cells in enumerate(data['atoms']):
        ids = {cell_unit[c] for c in cells}
        if len(ids) == 1 and -1 not in ids:
            u = next(iter(ids))
            atom_unit[a] = u
            members[u].append(a)
        elif len(ids) > 1:
            rejected.update(ids - {-1})
    links = defaultdict(Counter)
    union = Union(len(data['atoms']))
    for _, d, sinks, w in data['nets']:
        if not isinstance(d, int) or data['atom_of'][d] < 0:
            # Ports cannot establish internal connectivity but remain boundary pins.
            for s in sinks:
                if isinstance(s, int) and data['atom_of'][s] >= 0:
                    u = atom_unit[data['atom_of'][s]]
                    if u >= 0:
                        links[u]['incoming_weight4'] += w
            continue
        a = data['atom_of'][d]
        u = atom_unit[a]
        for s in sinks:
            b = data['atom_of'][s] if isinstance(s, int) else -1
            v = atom_unit[b] if b >= 0 else -1
            if u >= 0 and u == v:
                links[u]['internal_weight4'] += w
                union.join(a, b)
            else:
                if u >= 0:
                    links[u]['outgoing_weight4'] += w
                if v >= 0:
                    links[v]['incoming_weight4'] += w
    accepted = []
    audit = []
    for u, path in enumerate(paths):
        aa = members[u]
        sizes = Counter()
        for a in aa:
            sizes[union.find(a)] += len(data['atoms'][a])
        n = sum(sizes.values())
        volume = sum(links[u].values())
        cohesion = links[u]['internal_weight4'] / volume if volume else 0
        connected = max(sizes.values(), default=0) / n if n else 0
        reasons = []
        if u in rejected:
            reasons.append('crosses_physical_atom')
        if not cfg['operator_min_cells'] <= n <= cfg['operator_max_cells']:
            reasons.append('size_filter')
        if cohesion < cfg['operator_min_cohesion']:
            reasons.append('boundary_dominated')
        if connected < cfg['operator_min_connected_fraction']:
            reasons.append('internally_fragmented')
        info = dict(hierarchy=path, cells=n, atoms_count=len(aa), cohesion=cohesion,
                    largest_component_fraction=connected, accepted=not reasons,
                    rejection_reasons=reasons, **links[u])
        audit.append(info)
        if not reasons:
            demand = Counter()
            for a in aa:
                demand.update(data['atom_resources'][a])
            accepted.append(dict(info, atoms=aa, resources=dict(demand)))
    return accepted, audit


def contract(data, units):
    """Preserve all atoms, including coarse vertices without external hyperedges."""
    n = len(data['atoms'])
    mapping = [-1] * n
    groups = []
    for unit in units:
        group = list(unit['atoms'])
        if not group:
            raise ValueError('Empty operator')
        for a in group:
            if mapping[a] != -1:
                raise ValueError('Overlapping operator groups')
            mapping[a] = len(groups)
        groups.append(group)
    for a in range(n):
        if mapping[a] < 0:
            mapping[a] = len(groups)
            groups.append([a])
    atoms, resources = [], []
    for group in groups:
        atoms.append([c for a in group for c in data['atoms'][a]])
        r = Counter()
        for a in group:
            r.update(data['atom_resources'][a])
        resources.append(dict(r))
    edges = Counter()
    internal_count = internal_weight = 0
    for aa, w in data['edges']:
        projected = tuple(sorted({mapping[a] for a in aa}))
        if len(projected) > 1:
            edges[projected] += w
        else:
            internal_count += 1
            internal_weight += w
    coarse = dict(atoms=atoms, atom_resources=resources, edges=list(edges.items()),
                  active_atoms=list(range(len(groups))))
    totals = Counter()
    for r in resources:
        totals.update(r)
    original = Counter()
    for r in data['atom_resources']:
        original.update(r)
    assert totals == original
    assert sum(map(len, atoms)) == sum(map(len, data['atoms']))
    return coarse, groups, dict(original_atoms=n, coarse_vertices=len(groups),
        original_edges=len(data['edges']), coarse_edges=len(edges),
        cut_only_internal_edges_omitted=internal_count,
        cut_only_internal_weight4_omitted=internal_weight,
        original_graph_required_for_scoring=True, resource_totals=dict(totals))


def expand(groups, mapping, original_atoms):
    expanded = [[a for q in group for a in mapping[q]] for group in groups]
    label_groups(expanded, original_atoms)
    return expanded
