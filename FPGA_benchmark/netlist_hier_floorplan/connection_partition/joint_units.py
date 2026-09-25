"""Explicit, connectivity-validated coallocation units and atomic batch moves.

The caller proposes complete original-atom groups, including connecting logic.
No netlist transformation, coordinates, timing arc or latency claim is made.
"""
from collections import Counter, defaultdict
from structure_frontend import label_groups


def integrity(labels, units):
    """Check hard coallocation without interpreting or rewarding the objective."""
    split = []
    for u in units:
        aa = u['atoms']
        if not aa or any(not isinstance(a, int) or not 0 <= a < len(labels) for a in aa):
            raise ValueError('Invalid protected unit atoms')
        if len({labels[a] for a in aa}) != 1:
            split.append(u['hierarchy'])
    return dict(valid=not split, protected_units=len(units), split_units=len(split),
                split_unit_ids=split)


def require_intact(labels, units, stage):
    result = integrity(labels, units)
    if not result['valid']:
        raise ValueError(f'{stage}: split protected units: {result["split_unit_ids"][:8]}')
    return result


def load_protection(run):
    """Load a graph/config-bound protection bundle; enabled runs fail closed."""
    import json
    import pickle
    from improve import digest
    cfg_path = run/'source/resource_partition_config.json'
    enabled = cfg_path.exists() and json.loads(cfg_path.read_text()).get('joint_chains', {}).get('enabled', False)
    path = run/'protection_manifest.json'
    if not path.exists():
        if enabled:
            raise ValueError('Joint protection enabled but bundle is missing: '+str(run))
        return [], [], None
    manifest = json.loads(path.read_text())
    for name, expected in manifest['files'].items():
        if digest(run/name) != expected:
            raise ValueError('Changed protection input: '+name)
    with (run/'protection_units.pkl').open('rb') as f:
        units = pickle.load(f)
    with (run/'joint_chains.pkl').open('rb') as f:
        joint = pickle.load(f)
    return units, joint, manifest


def export_protection(out, data, labels, units, joint, module_ids, manifest):
    """Carry original leaf identities into downstream floorplan/physical audits."""
    import csv
    import gzip
    import json
    certificate = require_intact(labels, units, 'final export')
    rows = []
    with gzip.open(out/'joint_chain_cells.tsv.gz', 'wt') as f:
        writer = csv.writer(f, delimiter='\t', lineterminator='\n')
        writer.writerow(['chain', 'module', 'cell', 'primitive'])
        for u in joint:
            module = module_ids[labels[u['atoms'][0]]]
            rows.append(dict(chain=u['hierarchy'], module=module, cells=u['cells'],
                resources=u['resources'], discovery=u['discovery']))
            for a in u['atoms']:
                for c in data['atoms'][a]:
                    row = data['cells'][c]
                    writer.writerow([u['hierarchy'], module, row['cell_name'], row['primitive']])
    payload = dict(schema='local_joint_chains_v1', integrity=certificate, chains=rows,
                   protection_manifest=manifest,
                   physical_scope='Module coallocation only; multi-die regions or soft spills still require placement checks.')
    (out/'joint_chains.json').write_text(json.dumps(payload, indent=2)+'\n')
    return certificate


def validate_units(data, proposals, operators, resource_fits):
    owner = {}
    groups = []
    for i, p in enumerate(proposals):
        aa = set(p['atoms'])
        if not aa or len(aa) != len(p['atoms']):
            raise ValueError('Empty or duplicated coallocation atoms')
        for a in aa:
            if not 0 <= a < len(data['atoms']) or a in owner:
                raise ValueError('Invalid or overlapping coallocation groups')
            owner[a] = i
        groups.append(aa)
    for op in operators:
        targets = {owner[a] for a in op['atoms'] if a in owner}
        if targets and (len(targets) != 1 or not set(op['atoms']) <= groups[next(iter(targets))]):
            raise ValueError('Coallocation boundary splits an accepted operator')
    adjacency = defaultdict(set)
    for _, d, sinks, w in data['nets']:
        if w != 4 or not isinstance(d, int):
            continue
        a = data['atom_of'][d]
        if a not in owner:
            continue
        for s in sinks:
            b = data['atom_of'][s] if isinstance(s, int) else -1
            if b in owner and owner[a] == owner[b]:
                adjacency[a].add(b)
                adjacency[b].add(a)
    output = []
    for p, aa in zip(proposals, groups):
        # Each named stage must have a real data connection into this group.
        stages = [set(s) for s in p['stages']]
        if len(stages) < 2 or any(not s or not s <= aa for s in stages):
            raise ValueError('Missing or invalid chain stages')
        connected = set(stages[0]); todo = list(connected)
        while todo:
            a = todo.pop()
            for b in adjacency[a] - connected:
                connected.add(b); todo.append(b)
        if any(not connected.intersection(s) for s in stages[1:]):
            raise ValueError('No data connectivity between the proposed stages')
        demand = Counter()
        for a in aa:
            demand.update(data['atom_resources'][a])
        if not resource_fits(demand):
            raise ValueError('Coallocation unit exceeds a single die budget')
        output.append(dict(hierarchy=p['hierarchy'], atoms=sorted(aa), resources=dict(demand),
                           cells=sum(len(data['atoms'][a]) for a in aa),
                           stage_count=len(stages), kind='validated_coallocation'))
    return output


def protection_units(operators, joint):
    """Return disjoint units suitable for the existing contraction/refiner."""
    claimed = set()
    owner = {}
    for i,u in enumerate(joint):
        aa = set(u['atoms'])
        if not aa or len(aa) != len(u['atoms']) or claimed.intersection(aa):
            raise ValueError('Empty, duplicate or overlapping coallocation groups')
        claimed.update(aa)
        owner.update((a,i) for a in aa)
    for op in operators:
        overlap = claimed.intersection(op['atoms'])
        if overlap and len(overlap) != len(op['atoms']):
            raise ValueError('Partial accepted operator in coallocation unit')
        if len({owner[a] for a in overlap}) > 1:
            raise ValueError('Accepted operator spans multiple coallocation units')
    return list(joint) + [u for u in operators if not claimed.intersection(u['atoms'])]


def batch_move(data, groups, units, targets, resource_fits, protected=()):
    """Apply all proposals together; intermediate oversubscription is irrelevant.

This creates a candidate, not an objective-based acceptance decision. The caller
must rescore cut/logic costs and perform downstream regional capacity checks.
"""
    labels = label_groups(groups, len(data['atoms']))
    chosen = {}
    for u in units:
        if u['hierarchy'] not in targets:
            continue
        target = targets[u['hierarchy']]
        if not isinstance(target, int) or not 0 <= target < len(groups):
            raise ValueError('Invalid target module')
        for a in u['atoms']:
            if not isinstance(a, int) or not 0 <= a < len(labels):
                raise ValueError('Invalid coallocation atom')
            if a in chosen and chosen[a] != target:
                raise ValueError('Conflicting batch destinations')
            chosen[a] = target
    if set(targets) != {u['hierarchy'] for u in units if u['hierarchy'] in targets}:
        raise ValueError('Unknown coallocation target')
    for a, target in chosen.items():
        labels[a] = target
    revised = [[] for _ in groups]
    demand = [Counter() for _ in groups]
    for a, m in enumerate(labels):
        revised[m].append(a); demand[m].update(data['atom_resources'][a])
    label_groups(revised, len(data['atoms']))
    if not all(resource_fits(q) for q in demand):
        raise ValueError('Final batch exceeds module resource capacity')
    for u in protected:
        if len({labels[a] for a in u['atoms']}) != 1:
            raise ValueError('Final batch splits a protected unit')
    return revised
