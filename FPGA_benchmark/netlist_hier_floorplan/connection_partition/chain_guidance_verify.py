"""Independently recount exported ownership, capacity, chain integrity and cost."""
from collections import Counter
import csv
from fractions import Fraction
import gzip
import json
from pathlib import Path
import pickle

from improve import digest
from static_regions import RESOURCES, load_device


def verify(root, out):
    root, out = Path(root), Path(out)
    read = lambda p: json.loads(p.read_text())
    summary = read(out/'summary.json'); impl = out/'implementation_input'
    manifest = read(impl/'manifest.json'); physical = read(impl/'export/modules.json')
    logical = read(root/'balanced/selected/modules.json')
    parent_of = read(impl/'physical_to_logical.json')
    for name, expected in manifest['files'].items():
        path = (impl/name).resolve()
        assert impl.resolve() in path.parents and digest(path) == expected, name
    assert digest(root/'balanced/selected/leaf_cells.tsv.gz') == digest(impl/'logical_leaf_cells.tsv.gz')
    names = [m['module_id'] for m in physical['modules']]
    ids = {m: i for i, m in enumerate(names)}
    assert len(ids) == len(names) == manifest['module_count']
    counts = Counter(); parent_counts = Counter(); demands = {m: Counter() for m in names}
    cell_labels = []; unique = set()
    with gzip.open(impl/'export/leaf_cells.tsv.gz', 'rt') as fp, \
         gzip.open(impl/'logical_leaf_cells.tsv.gz', 'rt') as fl, \
         (impl/'membership.tsv').open() as fm:
        logical_rows = iter(csv.DictReader(fl, delimiter='\t'))
        memberships = iter(csv.DictReader(fm, delimiter='\t'))
        for i, row in enumerate(csv.DictReader(fp, delimiter='\t')):
            old = next(logical_rows); member = next(memberships)
            for key in ['cell_id', 'cell_name', 'primitive', 'original_hierarchy', *RESOURCES]:
                assert row[key] == old[key], (i, key)
            assert row['cell_id'] == f'c{i}' and row['cell_name'] not in unique
            unique.add(row['cell_name'])
            mid = row['module_id']; owner = parent_of.get(mid, mid)
            assert owner == old['module_id']
            assert member['module'] == mid and member['cell'] == row['cell_name'] and member['ref'] == row['primitive']
            counts[mid] += 1; parent_counts[owner] += 1; cell_labels.append(ids.get(mid, -1))
            if mid in demands:
                demands[mid].update({r: int(row[r]) for r in RESOURCES})
        assert next(logical_rows, None) is None and next(memberships, None) is None
    assert dict(counts) == manifest['counts'] and len(unique) == logical['validation']['all_cells']
    for m in physical['modules']:
        assert counts[m['module_id']] == m['cells']
        assert all(demands[m['module_id']][r] == m[r] for r in RESOURCES)
    for m in logical['modules']:
        assert parent_counts[m['module_id']] == m['cells']
        assert all(sum(q[r] for n, q in demands.items() if parent_of[n] == m['module_id']) == m[r] for r in RESOURCES)
    device = load_device(root/'cr.tsv'); regions = summary['core_plan']['regions']
    parent = read(root/'floorplan/solution.json')['regions']
    path_invariant=summary['core_plan'].get('cumulative_path_preservation')
    if path_invariant is not None:
        assert path_invariant['cell_slrs_unchanged']
        assert all(len(regions[m]['slrs'])==1 and regions[m]['slrs']==parent[parent_of[m]]['slrs'] for m in names)
        assert path_invariant['cumulative_path_term']==read(root/'floorplan/solution.json')['components']['cumulative_path_term']
    # Exact rational accumulation rather than the search's floating-point arrays.
    usage = {c: {r: Fraction(0) for r in RESOURCES} for c in device}
    for mid, q in demands.items():
        region = regions[mid]
        assert set(region['crs']) <= set(parent[parent_of[mid]]['crs'])
        for resource in RESOURCES:
            cap = sum(device[c]['resources'][resource] for c in region['crs'])
            assert cap == region['capacity'][resource]
            assert cap or not q[resource]
            for c in region['crs']:
                if device[c]['resources'][resource] and q[resource]:
                    usage[c][resource] += Fraction(q[resource], cap)
    limits = summary['core_plan']['limits']
    assert all(v <= Fraction(str(limits[r])) for row in usage.values() for r, v in row.items())
    with (root/'graph.pkl').open('rb') as f:
        data = pickle.load(f)
    labels = []
    for atom in data['atoms']:
        owners = {cell_labels[c] for c in atom}
        assert len(owners) == 1 and -1 not in owners
        labels.append(owners.pop())
    with (root/'protection_units.pkl').open('rb') as f:
        protected = pickle.load(f)
    for unit in protected:
        assert len({labels[a] for a in unit['atoms']}) == 1, unit['hierarchy']
    with (root/'joint_chains.pkl').open('rb') as f:
        joint = pickle.load(f)
    chain_groups = read(impl/'chain_groups.json')
    for unit in joint:
        assert names[labels[unit['atoms'][0]]] == chain_groups[unit['hierarchy']]
    # Rebuild the existing directed scorer from original net pins and exported
    # leaf owners, independently of the optimizer's chain-level aggregation.
    from balanced_physical import atom_resource
    from directed_model import DirectedModel
    slot = [labels[a]*len(RESOURCES)+RESOURCES.index(atom_resource(q))
            for a,q in enumerate(data['atom_resources'])]
    weights = Counter(); pins = Counter(); same = 0
    for _,driver,sinks,w in data['nets']:
        a = data['atom_of'][driver] if isinstance(driver,int) else -1
        if a < 0: continue
        for sink in sinks:
            b = data['atom_of'][sink] if isinstance(sink,int) else -1
            if b < 0: continue
            if a == b: same += 1; continue
            weights[slot[a],slot[b]] += w/4; pins[slot[a],slot[b]] += 1
    directed = dict(module_count=len(names),families={},coverage={'same_atom_pins':same},
        pairs=[dict(source=a,sink=b,weight=w,pins=pins[a,b]) for (a,b),w in weights.items()])
    model = DirectedModel(directed,device,read(root/'floorplan/source/directed_config.json'))
    components = model.components({f'S{i:02d}':regions[m] for i,m in enumerate(names)})
    cost = components['directed_term'] + components['branch_square_term']
    assert abs(cost-summary['search']['guided_directed_cost']) <= max(1e-5,abs(cost)*1e-10)
    result = dict(status='PASS', leaf_cells=len(cell_labels), physical_groups=len(names),
        logical_modules=len(logical['modules']), unique_membership=True, logical_owners_unchanged=True,
        protected_units=len(protected), joint_chains=len(joint), split_protected_units=0,
        rational_resource_audit=True, maximum_utilization={r:float(max(v[r] for v in usage.values())) for r in RESOURCES},
        independently_recomputed_directed_cost=cost, manifest_hashes=True,
        cumulative_path_invariant_verified=path_invariant is not None,
        native_Vivado_binding=False, placement_or_routing=False)
    (out/'independent_verification.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


if __name__ == '__main__':
    import sys
    print(json.dumps(verify(Path(sys.argv[1]),Path(sys.argv[2])),indent=2))
