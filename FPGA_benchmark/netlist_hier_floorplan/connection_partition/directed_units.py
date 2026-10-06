"""Name-independent, register-bounded cone candidates and exact C+L moves.

Cones are soft search objects, not new hard coallocation constraints. Original
physical atoms, protected chains, resource bounds and objective weights survive.
No coordinates, routed paths, fanout cutoff or module-name whitelist is used.
"""
from array import array
from collections import Counter, defaultdict
import math
import hashlib
import time

import numpy as np

from control_path_cost import PathModel
from improve import objective, soft_edges
from joint_units import require_intact
from macro_timing import expanded
from structure_frontend import label_groups

SCHEMA = 'directed-local-units-v1'
DEFAULTS = dict(max_cone_nodes=512, max_evaluations=20000)


def options(value=None):
    cfg = dict(DEFAULTS, **(value or {}))
    if set(cfg) != set(DEFAULTS):
        raise ValueError('Unknown directed-unit option')
    if any(type(v) is not int or v < 1 for v in cfg.values()):
        raise ValueError('Directed-unit work limits must be positive integers')
    return cfg


def csr(rows, values, n):
    order = np.argsort(rows, kind='stable')
    return np.r_[0, np.cumsum(np.bincount(rows, minlength=n))], values[order]


def build_topology(data, macro_metadata=None):
    """Reuse native macro semantics without constructing any physical model."""
    model = PathModel(data, dict(paths=[]), {})
    reg, comb, launch, layers, node_cells, extra, _ = expanded(model, data, macro_metadata)
    arrays = [launch, *layers]
    pairs = np.unique(np.concatenate([np.column_stack(p) for p in arrays]), axis=0)
    n = len(node_cells)
    pred_ptr, pred = csr(pairs[:, 1], pairs[:, 0], n)
    next_ptr, following = csr(pairs[:, 0], pairs[:, 1], n)
    cell_count = len(data['cells'])
    represented = np.unique(node_cells[pairs[:, 0]].astype(np.int64)*cell_count +
                            node_cells[pairs[:, 1]])
    escape = np.zeros(cell_count, dtype=bool)
    stats = Counter()
    # A missing/opaque/port consumer must not make a driver look exclusive.
    # Compare raw cell pairs in bounded batches to the expanded native graph.
    batch = []

    def flush():
        if not batch:
            return
        pp = np.asarray(batch, dtype=np.int64)
        keys = pp[:, 0]*cell_count + pp[:, 1]
        idx = np.searchsorted(represented, keys)
        found = idx < len(represented)
        if len(represented):
            found &= represented[np.minimum(idx, len(represented)-1)] == keys
        escape[pp[~found, 0]] = True
        stats['unmodeled_raw_branches'] += int((~found).sum())
        batch.clear()

    for _, driver, sinks, _ in data['nets']:
        if not isinstance(driver, int):
            stats['external_source_nets'] += 1
            continue
        for sink in sinks:
            if isinstance(sink, int):
                batch.append((driver, sink))
                if len(batch) >= 65536:
                    flush()
            else:
                escape[driver] = True
                stats['external_sink_branches'] += 1
    flush()
    supported = reg | comb
    coverage = dict(model.coverage, **extra)
    coverage.update(dict(stats), expanded_nodes=n, observed_paths=0,
        graph_model='macro_timing_v2', escape_guard_cells=int(escape.sum()),
        limitations=[
            'LUT/CARRY/MUX interiors are conservative cell-level dependencies.',
            'RAM/DSP use native active pin arcs; unsupported primitives remain opaque boundaries.',
            'Clock domains, false/multicycle paths and sensitization are not resolved.',
            'These are structural candidates, not a complete STA or functional-module certificate.'])
    # Macro state may be represented only by virtual nodes, not its cell node.
    covered_cells = set(map(int, node_cells[supported]))
    coverage['unsupported_cells'] = dict(Counter(c['primitive'] for i, c in enumerate(data['cells'])
                                                if i not in covered_cells))
    if macro_metadata:
        native_refs = {data['cells'][i]['primitive'] for i in macro_metadata['macro_cells']}
        coverage['opaque_source_pins'] = {k:v for k,v in model.coverage['opaque_source_pins'].items()
                                          if k not in native_refs}
    coverage.update(launch_edges=int(reg[pairs[:,0]].sum()),
                    comb_edges=int((~reg[pairs[:,0]]).sum()),topological_layers=len(layers))
    return dict(reg=reg, comb=comb, node_cells=node_cells, pred_ptr=pred_ptr, pred=pred,
                next_ptr=next_ptr, following=following, escape=escape, coverage=coverage)


def discover(data, graph, protected=(), cfg=None):
    """All capture boundaries and structural joins/forks seed exclusive cones.

Reverse admission requires ALL outputs of an interior node to remain inside the
cone. Reconvergent branches are admitted together; a broadcast with an outside
consumer stays at the boundary. Bounded cones are reported, never presented as
complete. Multiple roots may propose overlapping soft candidates.
"""
    cfg = options(cfg)
    reg, comb, cells = graph['reg'], graph['comb'], graph['node_cells']
    pp, pred, sp, succ = (graph[k] for k in ('pred_ptr', 'pred', 'next_ptr', 'following'))
    indegree, outdegree = np.diff(pp), np.diff(sp)
    roots = np.flatnonzero((reg & (indegree > 0)) |
                          (comb & ((indegree > 1) | (outdegree != 1))))
    atom_of = np.asarray(data['atom_of'], dtype=np.int64)
    node_atoms = atom_of[cells]
    supported_count = np.bincount(cells[comb], minlength=len(data['cells']))
    state_cells = set(map(int, cells[reg]))
    stats = Counter(roots_considered=len(roots))
    candidates = {}
    protected_of = {a: i for i, u in enumerate(protected) for a in u['atoms']}
    if len(protected_of) != sum(len(u['atoms']) for u in protected):
        raise ValueError('Overlapping protected units')
    for root in roots:
        root = int(root)
        inside = {root}
        queue = [root]
        admitted = Counter()
        bounded = False
        for node in queue:
            for p in pred[pp[node]:pp[node+1]]:
                p = int(p)
                if not comb[p] or graph['escape'][cells[p]]:
                    continue
                admitted[p] += 1
                if admitted[p] != outdegree[p] or p in inside:
                    continue
                if len(inside) >= cfg['max_cone_nodes']:
                    bounded = True
                    continue
                inside.add(p)
                queue.append(p)
        if bounded:
            stats['bounded_roots_skipped'] += 1
            continue
        counts = Counter(int(cells[v]) for v in inside if comb[v])
        touched = {int(node_atoms[v]) for v in inside if node_atoms[v] >= 0}
        atoms = {a for a in touched if all(c not in state_cells and supported_count[c] > 0 and
                    counts[c] == supported_count[c] for c in data['atoms'][a])}
        stats['partial_or_stateful_atom_occurrences'] += len(touched-atoms)
        # Never pull an entire storage/compute chain into a cone from one pin.
        for u in {protected_of[a] for a in atoms if a in protected_of}:
            members = set(protected[u]['atoms'])
            if not members <= atoms:
                stats['partial_protection_occurrences'] += len(atoms & members)
                atoms -= members
        if not atoms:
            stats['empty_movable_roots'] += 1
            continue
        anchors = touched-atoms
        for v in inside:
            for p in pred[pp[v]:pp[v+1]]:
                if int(p) not in inside:
                    anchors.add(int(node_atoms[p]))
        for v in succ[sp[root]:sp[root+1]] if comb[root] else ():
            anchors.add(int(node_atoms[v]))
        anchors = {a for a in anchors if a >= 0 and a not in atoms}
        key = tuple(sorted(atoms))
        if key in candidates:
            candidates[key]['anchors'].update(anchors)
            candidates[key]['root_count'] += 1
            continue
        candidates[key] = dict(atoms=list(key), anchors=anchors, root_count=1)
    rows = []
    for i, (key, row) in enumerate(sorted(candidates.items())):
        rows.append(dict(row, id=f'DU{i:07d}', anchors=sorted(row['anchors']),
                         cells=sum(len(data['atoms'][a]) for a in key)))
    stats.update(candidates=len(rows), candidate_atom_occurrences=sum(len(r['atoms']) for r in rows),
                 unique_candidate_atoms=len({a for r in rows for a in r['atoms']}))
    return rows, dict(schema=SCHEMA, **stats, graph_coverage=graph['coverage'], options=cfg,
        new_hard_units=0, uses_names=False, positions_assigned=False,
        semantics='Overlapping soft cones; original physical atoms and protected units remain indivisible.')


class MoveIndex:
    """Exact original hyperedge and logical-core deltas for multi-atom moves."""
    def __init__(self, data, groups, cores, protected, budget, cfg):
        self.data, self.budget, self.cfg, self.protected = data, budget, cfg, protected
        self.labels = label_groups(groups, len(data['atoms']))
        require_intact(self.labels, protected, 'directed refinement input')
        if not budget.audit(data, groups)['valid']:
            raise ValueError('Directed refinement input exceeds resource bounds')
        self.real = len(data['edges'])
        self.edges = data['edges'] + soft_edges(cores, cfg['core_soft_strength'])
        self.incident = [array('I') for _ in self.labels]
        for e, (pins, _) in enumerate(self.edges):
            for a in pins:
                self.incident[a].append(e)
        self.demands = defaultdict(Counter)
        self.volume = Counter()
        self.unit_of = {a:i for i,u in enumerate(protected) for a in u['atoms']}
        for a, m in enumerate(self.labels):
            self.demands[m].update(data['atom_resources'][a])
        for pins, w in data['edges']:
            for m in {self.labels[a] for a in pins}:
                self.volume[m] += w

    def metrics(self):
        c = objective(self.edges[:self.real], self.labels)[0]
        l = objective(self.edges[self.real:], self.labels)[0]
        return dict(weighted_km1=c, logical_core_loss=l,
                    J=self.cfg['cut_weight']*c+self.cfg['logical_core_weight']*l)

    def targets(self, candidate):
        result = {self.labels[a] for a in candidate['anchors']+candidate['atoms']}
        for a in candidate['atoms']:
            for e in self.incident[a]:
                if e < self.real:
                    result.update(self.labels[b] for b in self.edges[e][0])
        return sorted(result)

    def proposal(self, atoms, target, affinity_threshold):
        moved = {a for a in atoms if self.labels[a] != target}
        if not moved:
            return None, 'unchanged'
        for u in {self.unit_of[a] for a in moved if a in self.unit_of}:
            if any(a not in moved and self.labels[a] != target for a in self.protected[u]['atoms']):
                return None, 'protected_unit'
        addition = Counter()
        for a in moved:
            addition.update(self.data['atom_resources'][a])
        if not self.budget.fits(self.demands[target]+addition):
            return None, 'resource_budget'
        touched = {e for a in moved for e in self.incident[a]}
        real = [e for e in touched if e < self.real]
        volume = sum(self.edges[e][1] for e in real)
        shared = sum(self.edges[e][1] for e in real
                     if any(self.labels[a] == target for a in self.edges[e][0]))
        denominator = min(volume, self.volume[target])
        affinity = shared/denominator if denominator else 0.
        if affinity < affinity_threshold:
            return None, 'affinity'
        delta = [0., 0.]
        for e in touched:
            pins, weight = self.edges[e]
            old = len({self.labels[a] for a in pins})
            new = len({target if a in moved else self.labels[a] for a in pins})
            delta[e >= self.real] += weight*(new-old)/4
        change = self.cfg['cut_weight']*delta[0]+self.cfg['logical_core_weight']*delta[1]
        if change >= -1e-9:
            return None, 'non_improving_J'
        return dict(atoms=sorted(moved), target=target, delta_C=delta[0], delta_L=delta[1],
                    delta_J=change, affinity=affinity), None

    def apply(self, proposal):
        moved, target = proposal['atoms'], proposal['target']
        touched = {e for a in moved for e in self.incident[a] if e < self.real}
        for e in touched:
            pins, w = self.edges[e]
            for m in {self.labels[a] for a in pins}:
                self.volume[m] -= w
        for a in moved:
            self.demands[self.labels[a]].subtract(self.data['atom_resources'][a])
            self.demands[target].update(self.data['atom_resources'][a])
            self.labels[a] = target
        for e in touched:
            pins, w = self.edges[e]
            for m in {self.labels[a] for a in pins}:
                self.volume[m] += w


def refine(data, groups, candidates, cores, protected, budget, pcfg, affinity_threshold,
           seconds=60, max_moves=64, cfg=None, *, complete_pass=False, progress=None):
    cfg = options(cfg)
    if (not 0 <= affinity_threshold <= 1 or not math.isfinite(seconds) or seconds <= 0 or
            (max_moves is None and not complete_pass) or
            (max_moves is not None and (type(max_moves) is not int or max_moves < 1))):
        raise ValueError('Invalid directed refinement limits')
    started = time.monotonic()
    index = MoveIndex(data, groups, cores, protected, budget, pcfg)
    before = index.metrics()
    index_seconds = time.monotonic()-started
    started = time.monotonic()
    history, deferred, rejected = [], [], Counter()
    improving_proposals = 0
    evaluations = visited = completed = 0
    completed_ids = hashlib.sha256()
    # Larger fragmented cones are tried first to cross single-atom local minima.
    ordered = sorted(candidates, key=lambda r:(
        -len({index.labels[a] for a in r['atoms']+r['anchors']}), -len(r['atoms']), r['id']))
    ordered_ids = hashlib.sha256()
    for candidate in ordered:
        ordered_ids.update((candidate['id']+'\n').encode())
    last_progress = started
    def report():
        if progress:
            progress(dict(candidates_visited=visited, candidates_completed=completed,
                candidates_total=len(ordered), evaluations=evaluations,
                accepted_moves=len(history), deferred_moves=len(deferred),
                search_seconds=time.monotonic()-started))
    report()
    stop = 'all_candidates_visited'
    for candidate in ordered:
        if not complete_pass and len(history) >= max_moves:
            stop = 'move_limit'; break
        if not complete_pass and (evaluations >= cfg['max_evaluations'] or time.monotonic()-started >= seconds):
            stop = 'search_budget'; break
        visited += 1
        best = None
        fully_evaluated = True
        for target in index.targets(candidate):
            if not complete_pass and (evaluations >= cfg['max_evaluations'] or time.monotonic()-started >= seconds):
                fully_evaluated = False
                stop = 'search_budget'; break
            p, reason = index.proposal(candidate['atoms'], target, affinity_threshold)
            evaluations += 1
            if p is None:
                rejected[reason] += 1
            else:
                improving_proposals += 1
                if best is None or (p['delta_J'], p['delta_C'], p['target']) < (
                        best['delta_J'], best['delta_C'], best['target']):
                    best = p
        if best:
            if max_moves is None or len(history) < max_moves:
                index.apply(best)
                history.append(dict(best, candidate=candidate['id']))
            else:
                # Complete traversal continues without changing the partition.
                # These overlapping proposals are diagnostics, not additive gains.
                deferred.append(dict(best, candidate=candidate['id']))
        if fully_evaluated:
            completed += 1
            completed_ids.update((candidate['id']+'\n').encode())
        if progress and time.monotonic()-last_progress >= 5:
            report()
            last_progress = time.monotonic()
    report()
    # No new module labels are introduced, and at most one move is accepted
    # for each candidate. These are finite bounds, not arbitrary stop budgets.
    evaluation_bound = len(candidates)*len(groups)
    if complete_pass and not (visited == completed == len(candidates) and
            completed_ids.hexdigest() == ordered_ids.hexdigest() and
            evaluations <= evaluation_bound and stop == 'all_candidates_visited'):
        raise AssertionError('Incomplete directed pass')
    grouped = defaultdict(list)
    for a, m in enumerate(index.labels):
        grouped[m].append(a)
    revised = sorted(grouped.values(), key=min)
    require_intact(label_groups(revised, len(index.labels)), protected, 'directed refinement output')
    if not budget.audit(data, revised)['valid']:
        raise AssertionError('Directed refinement resource drift')
    after = index.metrics()
    for key, delta in [('J','delta_J'), ('weighted_km1','delta_C'), ('logical_core_loss','delta_L')]:
        if not math.isclose(after[key]-before[key], sum(p[delta] for p in history), abs_tol=1e-7):
            raise AssertionError('Directed refinement objective delta mismatch: '+key)
    return revised, dict(schema=SCHEMA, before=before, after=after, moves=history,
        deferred_improvements=deferred, improving_proposals=improving_proposals,
        acceptance_limit_reached=max_moves is not None and len(history) >= max_moves,
        evaluations=evaluations, candidates_visited=visited, candidates_completed=completed,
        candidates_total=len(candidates), complete_pass_requested=complete_pass,
        all_candidates_completed=completed == len(candidates),
        ordered_candidate_ids_sha256=ordered_ids.hexdigest(),
        completed_candidate_ids_sha256=completed_ids.hexdigest(),
        effective_limits=dict(seconds=None, max_evaluations=evaluation_bound,
                              max_moves=max_moves if max_moves is not None else len(candidates)) if complete_pass else
                         dict(seconds=seconds, max_evaluations=cfg['max_evaluations'], max_moves=max_moves),
        rejections=dict(rejected), stop_reason=stop, index_seconds=index_seconds,
        search_seconds=time.monotonic()-started, affinity_threshold=affinity_threshold,
        objective='cut_weight*C + logical_core_weight*L', new_objective_terms=0,
        resource_and_protection_checks='PASS', positions_assigned=False,
        scope=('One complete pass over cached candidates and their current target neighborhood; '
               'after the acceptance cap, continue read-only scoring and record deferred improvements. '
               'Not repeated convergence or a global optimum.' if complete_pass else
               'Bounded structural joint moves; connection admission and final selection remain in the caller.'))
