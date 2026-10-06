"""Resource-feasible physical grouping of intact chains inside fixed parents.

Logical partition labels never change. A bounded assignment MIP proposes chain
groups; exact directed branch cost ranks them against the all-parent fallback.
This is a subordinate guidance objective, not a rescore of parent D_hyper or STA.
"""
from collections import Counter, defaultdict
import math

import numpy as np

from balanced_physical import atom_resource, cdf_table
from edge_padding import region_from_crs
from static_regions import RESOURCES, fits, overlap_audit


def chain_nodes(data, labels, module_ids, joint, protected):
    from joint_units import require_intact
    require_intact(labels, protected, 'chain guidance logical input')
    nodes = {m: dict(parent=m, resources=Counter(), cells=0, chain=None) for m in module_ids}
    owner = [module_ids[m] for m in labels]
    claimed = set()
    for i, unit in enumerate(joint):
        aa = unit['atoms']
        if not aa or len(set(aa)) != len(aa) or claimed.intersection(aa):
            raise ValueError('Invalid or overlapping chains')
        if any(not isinstance(a, int) or not 0 <= a < len(labels) for a in aa):
            raise ValueError('Invalid chain atom')
        if len({labels[a] for a in aa}) != 1:
            raise ValueError('Chain crosses logical modules')
        node = f'J{i:04d}'
        if node in nodes:
            raise ValueError('Node ID collision')
        q = Counter()
        for a in aa:
            q.update(data['atom_resources'][a]); owner[a] = node
        if any(q[r] != unit['resources'].get(r, 0) for r in RESOURCES):
            raise ValueError('Chain resources disagree with original atoms')
        nodes[node] = dict(parent=module_ids[labels[aa[0]]], resources=q,
                           cells=sum(len(data['atoms'][a]) for a in aa), chain=unit['hierarchy'])
        claimed.update(aa)
    for a, node in enumerate(owner):
        if a not in claimed:
            nodes[node]['resources'].update(data['atom_resources'][a])
            nodes[node]['cells'] += len(data['atoms'][a])
    return nodes, owner


def directed_edges(data, owner):
    """Keep every modeled sink pin, including chain-internal connections."""
    edges = {}; coverage = Counter()
    resources = [RESOURCES.index(atom_resource(q)) for q in data['atom_resources']]
    for _, driver, sinks, weight in data['nets']:
        coverage['signal_sink_pins'] += len(sinks)
        a = data['atom_of'][driver] if isinstance(driver, int) else -1
        if a < 0:
            coverage['unlocated_source_pins'] += len(sinks)
            continue
        for sink in sinks:
            b = data['atom_of'][sink] if isinstance(sink, int) else -1
            if b < 0:
                coverage['unlocated_sink_pins'] += 1
                continue
            if a == b:
                coverage['same_atom_pins'] += 1
                continue
            pair = owner[a], owner[b]
            if pair not in edges:
                edges[pair] = np.zeros((len(RESOURCES), len(RESOURCES)))
            edges[pair][resources[a], resources[b]] += weight / 4
            coverage['modeled_distinct_atom_pins'] += 1
    assert coverage['signal_sink_pins'] == sum(coverage[k] for k in (
        'unlocated_source_pins', 'unlocated_sink_pins', 'same_atom_pins', 'modeled_distinct_atom_pins'))
    return edges, dict(coverage)


class BranchCost:
    """The existing directed expected-distance and branch-square formula."""
    def __init__(self, device, cfg):
        if cfg.get('directed_distance_model','raw_sink_pin_v1') != 'raw_sink_pin_v1':
            raise ValueError('Legacy chain/control movement cannot use boundary directed costs from fixed memberships; rebuild anchors for each changed membership. Use the fixed-membership floorplan flow.')
        self.device, self.cfg = device, cfg
        self.profile_cache, self.pair_cache = {}, {}
        self.dims = [max(d[k] for d in device.values()) for k in ('x', 'y', 'slr')]

    def profile(self, region):
        key = tuple(sorted(region['crs']))
        if key not in self.profile_cache:
            f = cdf_table(region, self.device)
            z0 = self.dims[0] + self.dims[1]
            p = np.clip(np.diff(np.c_[np.zeros(len(RESOURCES)), f[:, z0:],
                                     np.ones(len(RESOURCES))], axis=1), 0, 1)
            self.profile_cache[key] = f, p
        return self.profile_cache[key]

    def matrix(self, first, second):
        key = tuple(sorted(first['crs'])), tuple(sorted(second['crs']))
        if key not in self.pair_cache:
            f, p = self.profile(first); g, q = self.profile(second)
            xy = self.dims[0] + self.dims[1]
            local = np.maximum(0, f[:, :xy].sum(axis=1)[:, None] +
                               g[:, :xy].sum(axis=1)[None, :] - 2 * f[:, :xy] @ g[:, :xy].T)
            sep = abs(np.arange(self.dims[2] + 1)[:, None] - np.arange(self.dims[2] + 1)[None, :])
            value = self.cfg['directed_weight'] * (local + self.cfg['slr_distance_weight'] * p @ sep @ q.T)
            value += self.cfg['branch_square_weight'] * p @ np.maximum(0, sep - 1)**2 @ q.T
            self.pair_cache[key] = value
        return self.pair_cache[key]

    def total(self, edges, chosen):
        return sum(float(np.sum(w * self.matrix(chosen[a], chosen[b]))) for (a, b), w in edges.items())

    def unaries(self, chains, options, edges, chosen):
        incident = defaultdict(list)
        for (a, b), w in edges.items():
            incident[a].append((a, b, w))
            if a != b:
                incident[b].append((a, b, w))
        result = {}
        for node in chains:
            for k, region in enumerate(options):
                result[node, k] = sum(float(np.sum(w * self.matrix(
                    region if a == node else chosen[a], region if b == node else chosen[b])))
                    for a, b, w in incident[node])
        return result


def layouts(parent, device, cfg):
    """Candidate CR grids are internal proposals, not fixed device-wide slots."""
    xs = sorted({device[c]['x'] for c in parent['crs']})
    ys = sorted({device[c]['y'] for c in parent['crs']})
    proposals = []; seen = set()
    for nx in range(1, min(len(xs), cfg['max_children']) + 1):
        for ny in range(1, min(len(ys), cfg['max_children']) + 1):
            if not 2 <= nx * ny <= cfg['max_children']:
                continue
            cells = defaultdict(list)
            for c in parent['crs']:
                d = device[c]
                ix = min(nx - 1, xs.index(d['x']) * nx // len(xs))
                iy = min(ny - 1, ys.index(d['y']) * ny // len(ys))
                cells[ix, iy, d['slr']].append(c)
            if not 2 <= len(cells) <= cfg['max_children']:
                continue
            regions = [region_from_crs(crs, device) for _, crs in sorted(cells.items())]
            if any(r['area'] < cfg['min_child_crs'] for r in regions):
                continue
            signature = tuple(tuple(sorted(r['crs'])) for r in regions)
            if signature in seen:
                continue
            seen.add(signature)
            proposals.append(dict(name=f'grid{nx}x{ny}', regions=regions))
    ordered = sorted(proposals, key=lambda p: (
        abs(sum(r['area'] for r in p['regions']) / len(p['regions']) - cfg['target_child_crs']),
        p['name']))
    # Tight parents can require a coarser subdivision; never let the target-area
    # ordering exhaust the budget before testing both two-way orientations.
    coarse = [p for p in ordered if p['name'] in ('grid1x2', 'grid2x1')]
    return (coarse + [p for p in ordered if p not in coarse])[:cfg['max_layouts']]


def modules_for_nodes(nodes):
    return [dict(module_id=n, cells=u['cells'], **{r: u['resources'].get(r, 0) for r in RESOURCES})
            for n, u in nodes.items() if u['cells']]


def legal(nodes, chosen, device, limits):
    modules = modules_for_nodes(nodes)
    if not all(fits(m, chosen[m['module_id']], limits) for m in modules):
        return False
    return overlap_audit(modules, {m['module_id']: chosen[m['module_id']] for m in modules}, device, limits)['valid']


def assignment(nodes, chains, options, chosen, device, limits, costs, cfg):
    """Simultaneous assignment avoids falsely rejecting individually tight moves."""
    import gurobipy as gp
    model = gp.Model('intact_chain_regions'); model.Params.OutputFlag = 0
    model.Params.TimeLimit = cfg['mip_seconds_per_layout']
    model.Params.Threads = cfg['threads']; model.Params.Seed = cfg['seed']
    model.Params.MIPGap = 0.001
    variables = {}
    for node in chains:
        for k, region in enumerate(options):
            if fits(nodes[node]['resources'], region, limits):
                variables[node, k] = model.addVar(vtype=gp.GRB.BINARY)
        model.addConstr(gp.quicksum(v for (n, _), v in variables.items() if n == node) == 1)
    # Option zero is the complete inherited parent. It is always a legal fallback.
    for (node, k), v in variables.items():
        v.Start = int(k == 0)
    movable = set(chains)
    relevant = set().union(*(set(r['crs']) for r in options))
    for c in sorted(relevant):
        for resource in RESOURCES:
            if not device[c]['resources'][resource]:
                continue
            fixed = sum(u['resources'].get(resource, 0) / chosen[n]['capacity'][resource]
                        for n, u in nodes.items() if n not in movable and c in chosen[n]['crs']
                        and u['resources'].get(resource, 0))
            terms = [v * (nodes[n]['resources'].get(resource, 0) / options[k]['capacity'][resource])
                     for (n, k), v in variables.items() if c in options[k]['crs']
                     and nodes[n]['resources'].get(resource, 0)]
            model.addConstr(gp.quicksum(terms) + fixed <= limits[resource])
    model.setObjective(gp.quicksum(v * (costs[n, k] - costs[n, 0])
                                   for (n, k), v in variables.items()), gp.GRB.MINIMIZE)
    model.optimize()
    info = dict(status=int(model.Status), solutions=int(model.SolCount), seconds=float(model.Runtime))
    if not model.SolCount:
        model.dispose(); return None, info
    selected = {n: next(k for (a, k), v in variables.items() if a == n and v.X > 0.5) for n in chains}
    info.update(linearized_delta=float(model.ObjVal), gap=float(model.MIPGap))
    model.dispose()
    return selected, info


def plan(nodes, edges, parent_regions, device, directed_cfg, cfg, solver=assignment, progress=None):
    if directed_cfg.get('routed_density_profile'):
        raise ValueError('Routed density fitting is not supported')
    limits = directed_cfg['resource_limits']
    chosen = {n: parent_regions[u['parent']] for n, u in nodes.items()}
    if not legal(nodes, chosen, device, limits):
        raise ValueError('Baseline parent allocation is infeasible')
    cost = BranchCost(device, directed_cfg)
    baseline = cost.total(edges, chosen)
    trials = []; decisions = []
    for parent in sorted(parent_regions):
        chains = sorted(n for n, u in nodes.items() if u['chain'] and u['parent'] == parent)
        if len(chains) < cfg['min_parent_chains'] or parent_regions[parent]['area'] < cfg['min_parent_crs']:
            decisions.append(dict(parent=parent, status='below_guidance_threshold', chains=len(chains)))
            continue
        start = dict(chosen); best = dict(chosen); best_cost = cost.total(edges, chosen)
        best_tag = 'parent_fallback'
        for proposal in layouts(parent_regions[parent], device, cfg):
            options = [parent_regions[parent], *proposal['regions']]
            unary = cost.unaries(chains, options, edges, start)
            indices, detail = solver(nodes, chains, options, start, device, limits, unary, cfg)
            record = dict(parent=parent, layout=proposal['name'], solver=detail, accepted=False)
            if indices is not None:
                trial = dict(start)
                for node, k in indices.items():
                    trial[node] = options[k]
                feasible = legal(nodes, trial, device, limits)
                record['resource_valid'] = feasible
                if feasible:
                    value = cost.total(edges, trial)
                    record.update(directed_cost=value, guided_chains=sum(k != 0 for k in indices.values()))
                    if value < best_cost - 1e-6:
                        best, best_cost, best_tag = trial, value, proposal['name']; record['accepted'] = True
            trials.append(record)
            if progress:
                progress(record)
        chosen = best
        decisions.append(dict(parent=parent, status=best_tag, chains=len(chains),
            guided_chains=sum(set(chosen[n]['crs']) != set(parent_regions[parent]['crs']) for n in chains),
            fallback_chains=sum(set(chosen[n]['crs']) == set(parent_regions[parent]['crs']) for n in chains)))
    return chosen, dict(baseline_directed_cost=baseline, guided_directed_cost=cost.total(edges, chosen),
        decisions=decisions, trials=trials,
        objective='Existing directed distance plus multi-SLR branch square; parent D_hyper and partition J are frozen, not rescored.',
        optimality='Bounded grid proposals and linearized MIP assignments, exact directed reranking with parent fallback; not a global optimum.')


def physical_groups(nodes, owner, chosen, parents, data, logical_labels, module_ids, protected):
    """One disjoint leaf owner per physical Pblock; parent identities stay separate."""
    node_group = {}; regions = {}; parent_of = {}; chain_groups = {}
    for parent in module_ids:
        signatures = sorted({tuple(sorted(chosen[n]['crs'])) for n, u in nodes.items()
                             if u['parent'] == parent and u['cells']
                             and set(chosen[n]['crs']) != set(parents[parent]['crs'])})
        mapping = {sig: f'{parent}G{i:02d}' for i, sig in enumerate(signatures)}
        for node, unit in nodes.items():
            if unit['parent'] != parent or not unit['cells']:
                continue
            crs = set(chosen[node]['crs'])
            if not crs <= set(parents[parent]['crs']):
                raise ValueError('Child core leaves its logical parent')
            group = parent if crs == set(parents[parent]['crs']) else mapping[tuple(sorted(crs))]
            node_group[node] = group; parent_of[group] = parent; regions[group] = chosen[node]
            if unit['chain']:
                chain_groups[unit['chain']] = group
    names = sorted(regions); ids = {name: i for i, name in enumerate(names)}
    groups = [[] for _ in names]; labels = []
    for a, node in enumerate(owner):
        group = node_group[node]
        if parent_of[group] != module_ids[logical_labels[a]]:
            raise ValueError('Logical parent membership changed')
        labels.append(ids[group]); groups[ids[group]].append(a)
    from joint_units import require_intact
    audit = require_intact(labels, protected, 'physical chain groups')
    modules = []
    for name, aa in zip(names, groups):
        q = Counter()
        for a in aa:
            q.update(data['atom_resources'][a])
        modules.append(dict(module_id=name, logical_parent=parent_of[name],
            cells=sum(len(data['atoms'][a]) for a in aa),
            chain_count=sum(g == name for g in chain_groups.values()),
            **{r: q[r] for r in RESOURCES}))
    return dict(modules=modules, regions=regions, parent_of=parent_of, labels=labels,
                groups=groups, chain_groups=chain_groups, integrity=audit)
