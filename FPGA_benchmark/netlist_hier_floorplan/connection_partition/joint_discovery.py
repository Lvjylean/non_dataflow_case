"""Conservative discovery of local memory/operator chains on original atoms.

Hierarchy bounds traversal; only directed data corridors establish membership.
Existing FFs are traversed, never changed. These are not single-cycle STA paths.
"""
from collections import Counter, defaultdict, deque

from joint_units import validate_units
from structure_frontend import Union

DEFAULTS = dict(enabled=True, max_scope_cells=32768, max_memory_cells=1024,
                max_bridge_hops=8, max_bridge_atoms=4096, max_data_net_sinks=64,
                min_data_nets=8, memory_scope_fraction=.9)


def discover_joint(data, operators, config, resource_fits):
    cfg = dict(DEFAULTS, **config)
    audit = dict(schema='local_joint_chains_v1', configuration=cfg, scopes=[],
                 memories=[], chains=[], enabled=cfg['enabled'])
    if not cfg['enabled']:
        return [], audit
    for k in ('max_scope_cells', 'max_memory_cells', 'max_bridge_hops',
              'max_bridge_atoms', 'max_data_net_sinks', 'min_data_nets'):
        if not isinstance(cfg[k], int) or cfg[k] < 1:
            raise ValueError('Invalid joint discovery limit: '+k)
    if not .5 < cfg['memory_scope_fraction'] <= 1:
        raise ValueError('Memory scope fraction must be in (0.5, 1].')
    cells, atoms = data['cells'], data['atoms']
    ancestors = set()
    for u in operators:
        p = u['hierarchy'].rpartition('/')[0]
        while p:
            ancestors.add(p); p = p.rpartition('/')[0]
    sizes = Counter()
    for a, cc in enumerate(atoms):
        for c in cc:
            p = cells[c]['cell_name'].rpartition('/')[0]
            while p:
                if p in ancestors:
                    sizes[p] += 1
                p = p.rpartition('/')[0]
    eligible = {p for p in ancestors if sizes[p] <= cfg['max_scope_cells']}
    parents = set()
    for p in sorted(eligible, key=lambda s: (s.count('/'), s)):
        q = p.rpartition('/')[0]
        while q and q not in parents:
            q = q.rpartition('/')[0]
        if not q:
            parents.add(p)
    scopes = {p: [] for p in sorted(parents)}
    atom_scope = {}
    exact = defaultdict(set)
    crossed = set()
    # The largest size-bounded ancestor includes wrapper registers without
    # assuming a fixed hierarchy depth. It is not contracted as a whole.
    for a, cc in enumerate(atoms):
        found = set()
        for c in cc:
            path = cells[c]['cell_name'].rpartition('/')[0]
            exact[path].add(a)
            while path and path not in parents:
                path = path.rpartition('/')[0]
            found.add(path or None)
        if len(found) == 1 and None not in found:
            p = next(iter(found)); scopes[p].append(a); atom_scope[a] = p
        elif len(found) > 1:
            crossed.update(found - {None})
    for p in list(scopes):
        n = sum(len(atoms[a]) for a in scopes[p])
        reasons = ([] if p not in crossed else ['crosses_physical_atom'])
        if n > cfg['max_scope_cells']:
            reasons.append('scope_too_large')
        audit['scopes'].append(dict(hierarchy=p, cells=n, rejection_reasons=reasons))
        if reasons:
            for a in scopes.pop(p):
                atom_scope.pop(a, None)
    op_by_scope = defaultdict(list)
    op_atoms = set()
    for u in operators:
        op_atoms.update(u['atoms'])
        pp = {atom_scope.get(a) for a in u['atoms']}
        if len(pp) == 1 and None not in pp:
            op_by_scope[next(iter(pp))].append(u)
    # A small exact-parent memory wrapper may include LUT glue, but never part
    # of an accepted operator or an atom crossing the wrapper boundary.
    memories = []
    mem_owner = {}
    for p, aa in sorted(exact.items()):
        if not any(data['atom_resources'][a].get(r, 0) for a in aa for r in ('URAM', 'BRAM18')):
            continue
        if not p:
            continue
        n = sum(len(atoms[a]) for a in aa)
        reason = None
        if n > cfg['max_memory_cells']:
            reason = 'memory_wrapper_too_large'
        elif aa & op_atoms:
            reason = 'overlaps_operator'
        elif any(cells[c]['cell_name'].rpartition('/')[0] != p for a in aa for c in atoms[a]):
            reason = 'crosses_physical_atom'
        if reason:
            audit['memories'].append(dict(hierarchy=p, accepted=False, reason=reason))
            continue
        i = len(memories)
        memories.append(dict(hierarchy=p, atoms=sorted(aa)))
        for a in aa:
            mem_owner[a] = i
    # Compare recognized local compute consumers, not global readback muxes or
    # address/control fan-in. Other consumers remain visible in the audit; this
    # preference does not assert that a memory is private or semantically local.
    affinity = defaultdict(Counter)
    data_links = []
    memory_pins = []
    fanin = {}
    for ni, (_, driver, sinks, w) in enumerate(data['nets']):
        a = data['atom_of'][driver] if isinstance(driver, int) else -1
        if w != 4:
            continue
        for s in sinks:
            b = data['atom_of'][s] if isinstance(s, int) else -1
            if b >= 0 and a != b:
                source = a if a >= 0 else ('external',driver)
                previous = fanin.setdefault(b,source)
                if previous != source:
                    fanin[b] = -2
            if a in mem_owner and mem_owner.get(b) != mem_owner[a]:
                memory_pins.append((mem_owner[a],b))
        if a < 0 or len(sinks) > cfg['max_data_net_sinks']:
            continue
        for s in sinks:
            b = data['atom_of'][s] if isinstance(s, int) else -1
            if b >= 0 and a != b and (a in atom_scope or a in mem_owner) and (b in atom_scope or b in mem_owner):
                data_links.append((a, b, ni))
    transparent = {a for a in atom_scope if a not in op_atoms and a not in mem_owner
        and (all(cells[c]['primitive'].startswith('FD') for c in atoms[a]) or
             (fanin.get(a) != -2 and all(cells[c]['primitive'].startswith(('LUT','BUF')) for c in atoms[a])))}
    for i,b in memory_pins:
        # A multi-bank readback mux is a combining boundary, not a transparent
        # link to the local arithmetic operand. Its output traffic stays external.
        affinity[i][atom_scope.get(b) if b in transparent or b in op_atoms else None] += 1
    assigned = defaultdict(list)
    for i, mem in enumerate(memories):
        counts = affinity[i]
        known = [(n, p) for p, n in counts.items() if p in op_by_scope]
        n, p = max(known, default=(0, ''))
        local_pins = sum(count for count, _ in known)
        fraction = n / local_pins if local_pins else 0
        ok = bool(n and fraction >= cfg['memory_scope_fraction'])
        audit['memories'].append(dict(hierarchy=mem['hierarchy'], accepted=ok,
            scope=p or None, output_scope_fraction=fraction,
            local_compute_sink_pins=local_pins, other_sink_pins=sum(counts.values())-local_pins,
            reason=None if ok else 'shared_or_unresolved_data_consumers'))
        if ok:
            assigned[p].append(mem)
    # Materialize only allowed local edges; shared memories never connect scopes.
    local_owner = dict(atom_scope)
    for p, mm in assigned.items():
        for mem in mm:
            for a in mem['atoms']:
                local_owner[a] = p
    links = defaultdict(list)
    for a, b, ni in data_links:
        p = local_owner.get(a)
        if p in assigned and local_owner.get(b) == p:
            links[p].append((a, b, ni))
    proposals = []
    evidence = []
    for p in sorted(assigned):
        stages = sorted(op_by_scope[p], key=lambda u: u['hierarchy']) + assigned[p]
        owner = {a: i for i, u in enumerate(stages) for a in u['atoms']}
        allowed = set(owner)
        for a in scopes[p]:
            # Do not pass through unaccepted arithmetic, memory, or carry atoms.
            if a in transparent:
                allowed.add(a)
        adj, rev = defaultdict(set), defaultdict(set)
        edges = []
        for a, b, ni in links[p]:
            if a in allowed and b in allowed and not (a in owner and owner.get(b) == owner[a]):
                adj[a].add(b); rev[b].add(a); edges.append((a, b, ni))

        def distances(seeds, graph):
            dist = {a: 0 for a in seeds}; todo = deque(sorted(seeds))
            while todo:
                a = todo.popleft()
                if dist[a] >= cfg['max_bridge_hops'] + 1:
                    continue
                for b in sorted(graph.get(a, ())):
                    if b not in dist:
                        dist[b] = dist[a] + 1
                        if b not in owner:
                            todo.append(b)
                if len(dist) > cfg['max_bridge_atoms'] + len(owner):
                    return None
            return dist

        forward = [distances(u['atoms'], adj) for u in stages]
        backward = [distances(u['atoms'], rev) for u in stages]
        pairs = []
        union = Union(len(stages))
        for i, f in enumerate(forward):
            if f is None:
                continue
            destinations = {owner[a] for a in f if a in owner} - {i}
            for j in sorted(destinations):
                b = backward[j]
                if b is None:
                    continue
                corridor = {a for a in f.keys() & b.keys() if a not in owner and
                            f[a] + b[a] <= cfg['max_bridge_hops'] + 1}
                first, last = set(), set()
                for a, z, ni in edges:
                    if a in f and z in b and f[a] + 1 + b[z] <= cfg['max_bridge_hops'] + 1:
                        if owner.get(a) == i and (z in corridor or owner.get(z) == j):
                            first.add(ni)
                        if owner.get(z) == j and (a in corridor or owner.get(a) == i):
                            last.add(ni)
                width = min(len(first), len(last))
                if width < cfg['min_data_nets'] or len(corridor) > cfg['max_bridge_atoms']:
                    continue
                pairs.append(dict(source=i, sink=j, data_nets_lower_bound=width, atoms=sorted(corridor)))
        operator_count = len(op_by_scope[p])
        # Shared banks cannot glue independent arithmetic chains together even
        # when those chains happen to share one small hierarchy scope.
        for pair in pairs:
            if max(pair['source'],pair['sink']) < operator_count:
                union.join(pair['source'],pair['sink'])
        memory_components = defaultdict(set)
        for pair in pairs:
            i,j=pair['source'],pair['sink']
            if i < operator_count <= j:
                memory_components[j].add(union.find(i))
            elif j < operator_count <= i:
                memory_components[i].add(union.find(j))
        shared = {i for i,components in memory_components.items() if len(components)>1}
        audit.setdefault('shared_within_scope',[]).extend(stages[i]['hierarchy'] for i in sorted(shared))
        pairs = [pair for pair in pairs if pair['source'] not in shared and pair['sink'] not in shared
                 and min(pair['source'],pair['sink']) < operator_count]
        for pair in pairs:
            union.join(pair['source'],pair['sink'])
        components = defaultdict(list)
        for i in range(len(stages)):
            components[union.find(i)].append(i)
        for ids in sorted(components.values(), key=min):
            if len(ids) < 2 or not any(i < len(op_by_scope[p]) for i in ids) or not any(i >= len(op_by_scope[p]) for i in ids):
                continue
            selected = [pair for pair in pairs if pair['source'] in ids and pair['sink'] in ids]
            bridge = {a for pair in selected for a in pair['atoms']}
            aa = sorted({a for i in ids for a in stages[i]['atoms']} | bridge)
            demand = Counter()
            for a in aa:
                demand.update(data['atom_resources'][a])
            reasons = []
            if len(bridge) > cfg['max_bridge_atoms']:
                reasons.append('bridge_budget')
            if not resource_fits(demand):
                reasons.append('single_die_resource_budget')
            record = dict(hierarchy=p+'/@joint_'+str(min(ids)), scope=p,
                stages=[dict(hierarchy=stages[i]['hierarchy'], kind='operator' if i < len(op_by_scope[p]) else 'memory') for i in ids],
                resources=dict(demand), cells=sum(len(atoms[a]) for a in aa),
                bridge_atoms=len(bridge), stage_connections=[dict(
                    source=stages[x['source']]['hierarchy'], sink=stages[x['sink']]['hierarchy'],
                    data_nets_lower_bound=x['data_nets_lower_bound'], bridge_atoms=len(x['atoms'])) for x in selected],
                accepted=not reasons, rejection_reasons=reasons)
            audit['chains'].append(record)
            if not reasons:
                proposals.append(dict(hierarchy=record['hierarchy'], atoms=aa,
                    stages=[stages[i]['atoms'] for i in ids]))
                evidence.append(record)
    # A shared intermediate must not silently bind otherwise distinct chains.
    counts = Counter(a for p in proposals for a in p['atoms'])
    kept, kept_evidence = [], []
    for p, row in zip(proposals, evidence):
        if any(counts[a] > 1 for a in p['atoms']):
            row['accepted'] = False; row['rejection_reasons'].append('shared_corridor')
        else:
            kept.append(p); kept_evidence.append(row)
    units = validate_units(data, kept, operators, resource_fits)
    for u, row in zip(units, kept_evidence):
        u.update(kind='automatic_joint_chain', discovery=row)
    audit['accepted_chains'] = len(units)
    audit['protected_cells'] = sum(u['cells'] for u in units)
    return units, audit
