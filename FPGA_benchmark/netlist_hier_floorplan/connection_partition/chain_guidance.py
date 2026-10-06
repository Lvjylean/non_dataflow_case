"""Create independent physical groups without changing logical partition owners."""
import argparse
from collections import Counter
import csv
import gzip
import json
from pathlib import Path
import pickle
import shutil
import time

from chain_regions import chain_nodes, directed_edges, plan, physical_groups
from edge_padding import expand, regions_tcl, region_from_crs
from improve import digest, labels_for, objective
from joint_units import load_protection, require_intact, export_protection
import partition as base
from static_regions import RESOURCES, load_device, overlap_audit


def load(path):
    return json.loads(Path(path).read_text())


def dump(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')


def soft_regions(physical, baseline_soft, device):
    """Preserve other envelopes; child extensions stay within the parent envelope."""
    expanded, detail = expand(physical['modules'], dict(regions=physical['regions']), device)
    answer = {}
    for mid, core in physical['regions'].items():
        parent = physical['parent_of'][mid]
        if mid == parent:
            crs = baseline_soft[parent]['crs']
        else:
            crs = set(expanded[mid]['crs']) & set(baseline_soft[parent]['crs'])
        if not set(core['crs']) <= set(crs):
            raise ValueError('Soft envelope lost child core cells')
        region = region_from_crs(crs, device)
        region.pop('capacity')
        region.update(core_crs=core['crs'], padding_crs=sorted(set(crs) - set(core['crs'])),
                      geometry_role='soft_allowance_only')
        answer[mid] = region
    return answer, detail


def export_input(out, root, floorplan, data, logical_labels, logical_meta, physical,
                 soft, detail, protected, joint, protection_manifest, summary):
    """Rebuild all physical metadata; never relabel an old connection table."""
    impl = out/'implementation_input'; impl.mkdir()
    export = impl/'export'; export.mkdir()
    shutil.copytree(root/'balanced/selected', impl/'logical_export')
    shutil.copy2(root/'balanced/selected/leaf_cells.tsv.gz', impl/'logical_leaf_cells.tsv.gz')
    labels = physical['labels']; names = [m['module_id'] for m in physical['modules']]
    km1, cut = objective(data['edges'], labels)
    owners, modules, pairs, ports, metrics = base.summaries(data,
        dict(groups=physical['groups'], membership=labels, weighted_km1=km1, weighted_cut=cut))
    mapping = {f'P{i:02d}': name for i, name in enumerate(names)}
    reference = {m['module_id']: m for m in physical['modules']}
    for module in modules:
        module['module_id'] = mapping[module['module_id']]
        checked = reference[module['module_id']]
        assert all(module[r] == checked[r] for r in ('cells', *RESOURCES))
        module.update(logical_parent=checked['logical_parent'], chain_count=checked['chain_count'])
    connections = [dict(source=mapping.get(a, a), sink=mapping.get(b, b), **dict(v))
                   for (a, b), v in sorted(pairs.items())]
    portrows = [dict(source=mapping.get(a, a), sink=mapping.get(b, b), **dict(v))
                for (a, b), v in sorted(ports.items())]
    counts = Counter(); totals = Counter(); projected = Counter()
    fields = ['cell_id', 'cell_name', 'primitive', 'original_hierarchy', 'module_id', *RESOURCES]
    with gzip.open(export/'leaf_cells.tsv.gz', 'wt') as stream, (impl/'membership.tsv').open('w') as mem:
        writer = csv.DictWriter(stream, fieldnames=fields, delimiter='\t'); writer.writeheader()
        member = csv.writer(mem, delimiter='\t', lineterminator='\n')
        member.writerow(['cell', 'module', 'resource', 'ref'])
        for i, (cell, old) in enumerate(zip(data['cells'], owners)):
            assert cell['cell_id'] == f'c{i}'
            mid = mapping.get(old, old); resources = base.resources(cell['primitive'])
            counts[mid] += 1; totals.update(resources)
            if mid in physical['parent_of']:
                parent = physical['parent_of'][mid]
                assert parent == logical_meta['modules'][logical_labels[data['atom_of'][i]]]['module_id']
                projected[parent] += 1
            writer.writerow(dict(cell, module_id=mid, **{r: resources.get(r, 0) for r in RESOURCES}))
            resource = next((r for r in ('DSP', 'URAM', 'BRAM18', 'FF', 'LUT', 'CARRY8', 'MUXF8', 'MUXF7')
                             if resources.get(r)), 'OTHER')
            member.writerow([cell['cell_name'], mid, resource, cell['primitive']])
    for module in logical_meta['modules']:
        assert projected[module['module_id']] == module['cells']
        children = [m for m in modules if m['logical_parent'] == module['module_id']]
        assert all(sum(m[r] for m in children) == module[r] for r in RESOURCES)
    assert sum(counts.values()) == len(data['cells'])
    assert all(totals[r] == data['totals'].get(r, 0) for r in RESOURCES)
    base.write_table(export/'module_resources.tsv', modules,
        ['module_id', 'logical_parent', 'cells', 'chain_count', *RESOURCES, 'floorplan_eligible'])
    base.write_table(export/'module_connections.tsv', connections,
        ['source', 'sink', 'nets', 'sink_pin_connections', 'weighted_nets', 'data_nets', 'control_nets'])
    base.write_table(export/'port_connections.tsv', portrows, ['source', 'sink', 'nets', 'sink_pin_connections'])
    certificate = export_protection(export, data, labels, protected, joint, names, protection_manifest)
    meta = dict(schema='physical-guidance-groups-v1', modules=modules, connections=connections,
        input_dcp=logical_meta['input_dcp'], input_sha256=logical_meta['input_sha256'],
        logical_partition=dict(module_count=len(logical_meta['modules']),
            objective=logical_meta['partition_objective'], unchanged=True, export='logical_export'),
        physical_group_metrics=metrics, infrastructure={k: v for k, v in counts.items() if k not in names},
        validation=dict(all_cells=len(data['cells']), resources_conserved=True, unique_ordered_ids=True,
                        logical_parent_projection=True, protection=certificate),
        physical_validation='Static estimates and exact soft geometry only; no placement/routing.')
    dump(export/'modules.json', meta)
    dump(export/'static_regions.json', summary['core_plan'])
    dump(impl/'core_solution.json', summary['core_plan'])
    shutil.copy2(floorplan/'solution.json', impl/'parent_core_solution.json')
    (impl/'regions.tcl').write_text(regions_tcl(soft))
    shutil.copy2(root/'implementation_input/soft_region_adapter.tcl', impl/'soft_region_adapter.tcl')
    dump(impl/'edge_padding.json', dict(proposals=detail, actual_padding={m: r['padding_crs'] for m, r in soft.items()},
        scope='Unchanged parent envelopes; child extensions are limited to their parent envelope. Geometry only.'))
    dump(impl/'physical_to_logical.json', physical['parent_of'])
    dump(impl/'chain_groups.json', physical['chain_groups'])
    dump(impl/'manifest.json', dict(status='PASS', input_dcp=meta['input_dcp'], input_sha256=meta['input_sha256'],
        module_count=len(modules), logical_module_count=len(logical_meta['modules']), counts=dict(counts),
        logical_membership_preserved=True, protection=certificate,
        files={str(p.relative_to(impl)): digest(p) for p in impl.rglob('*') if p.is_file()},
        scope='Disjoint physical Pblock memberships; original logical owners retained separately; no netlist edit or P&R.'))


def run(root, out, config=None):
    started = time.monotonic(); root = Path(root).resolve(); out = Path(out).resolve()
    floorplan = root/'floorplan'
    if out.exists():
        raise FileExistsError(out)
    cfg = load(config or Path(__file__).with_name('chain_guidance_config.json'))
    core = load(floorplan/'solution.json'); meta = load(root/'balanced/selected/modules.json')
    if core['status'] != 'feasible' or not core['overlap']['valid']:
        raise ValueError('A validated parent core floorplan is required')
    if load(floorplan/'verification.json')['status'] != 'PASS':
        raise ValueError('Parent floorplan verification did not pass')
    if digest(root/'balanced/selected/leaf_cells.tsv.gz') != digest(root/'implementation_input/export/leaf_cells.tsv.gz'):
        raise ValueError('Parent floorplan membership differs from partition')
    source_files = [root/'graph.pkl', root/'cr.tsv', floorplan/'solution.json',
                    root/'balanced/selected/modules.json', root/'balanced/selected/leaf_cells.tsv.gz',
                    root/'protection_manifest.json', root/'implementation_input/manifest.json']
    immutable = {str(p): digest(p) for p in source_files}
    protected, joint, manifest = load_protection(root)
    if not manifest or not joint:
        raise ValueError('A validated joint-chain bundle is required')
    with (root/'graph.pkl').open('rb') as stream:
        data = pickle.load(stream)
    groups = load(root/'balanced/candidates'/meta['selected_candidate']/'groups.json')
    labels = labels_for(data, groups); ids = [m['module_id'] for m in meta['modules']]
    device = load_device(root/'cr.tsv'); directed_cfg = load(floorplan/'source/directed_config.json')
    nodes, owner = chain_nodes(data, labels, ids, joint, protected)
    for module in meta['modules']:
        assert all(sum(u['resources'].get(r, 0) for u in nodes.values() if u['parent'] == module['module_id'])
                   == module[r] for r in RESOURCES)
    edges, coverage = directed_edges(data, owner)
    out.mkdir(parents=True)
    dump(out/'config.json', cfg)
    algorithm = {str(p.resolve()): digest(p) for p in Path(__file__).resolve().parent.iterdir()
                 if p.is_file() and not p.name.startswith('.')}
    dump(out/'source_binding.json', dict(files=algorithm, configuration=cfg,
        partition_run=str(root), parent_floorplan=str(floorplan)))
    def progress(record):
        with (out/'progress.jsonl').open('a') as stream:
            stream.write(json.dumps(record) + '\n')
        print(json.dumps(record), flush=True)
    chosen, search = plan(nodes, edges, core['regions'], device, directed_cfg, cfg, progress=progress)
    expected = core['components']['directed_term'] + core['components']['branch_square_term']
    assert abs(search['baseline_directed_cost'] - expected) <= max(1e-5, abs(expected) * 1e-10)
    physical = physical_groups(nodes, owner, chosen, core['regions'], data, labels, ids, protected)
    audit = overlap_audit(physical['modules'], physical['regions'], device, directed_cfg['resource_limits'])
    assert audit['valid']
    old_soft = load(floorplan/'soft/solution.json')['regions']
    soft, padding = soft_regions(physical, old_soft, device)
    unchanged = [m for m in ids if m in physical['regions'] and
                 not any(n != m and p == m for n, p in physical['parent_of'].items())]
    assert all(physical['regions'][m] == core['regions'][m] and set(soft[m]['crs']) == set(old_soft[m]['crs']) for m in unchanged)
    path_preservation=None
    if directed_cfg.get('cumulative_paths',{}).get('enabled',False):
        # Subdivision within a single parent die leaves every cell's SLR fixed.
        assert all(len(core['regions'][u['parent']]['slrs'])==1 and
                   chosen[n]['slrs']==core['regions'][u['parent']]['slrs'] for n,u in nodes.items())
        path_preservation=dict(cell_slrs_unchanged=True,
            cumulative_path_term=core['components']['cumulative_path_term'],
            semantics='Parent path term is invariant under same-SLR child guidance.')
    core_plan = dict(status='feasible', regions=physical['regions'], overlap=audit,
        limits=directed_cfg['resource_limits'], logical_parent_J=core['objective'],
        objective=None, guidance_directed_cost=search['guided_directed_cost'],
        cumulative_path_preservation=path_preservation,
        objective_role='Parent J stays frozen; child guidance reports only exact directed cost. No redefined partition or full-J claim.')
    summary = dict(status='PASS', schema=cfg['schema'], logical_module_count=len(ids),
        physical_group_count=len(physical['modules']), logical_membership_unchanged=True,
        parent_regions_unchanged=True, unchanged_parent_envelopes=unchanged,
        chains=len(joint), protected_units=len(protected), split_protected_units=0,
        modules=physical['modules'], parent_of=physical['parent_of'], core_plan=core_plan,
        soft_regions=soft, search=search, coverage=coverage, source_files=immutable,
        actual_congestion_or_timing='UNMEASURED: no new placement or routing.',
        resource_accounting='Disjoint physical groups plus remainder, projected on cores; parent totals are not added again.')
    assert digest(Path(meta['input_dcp'])) == meta['input_sha256']
    export_input(out, root, floorplan, data, labels, meta, physical, soft, padding,
                 protected, joint, manifest, summary)
    summary['seconds'] = time.monotonic() - started
    dump(out/'summary.json', summary)
    dump(out/'chain_assignments.json', [dict(node=n, chain=u['chain'], parent=u['parent'],
        physical_group=physical['chain_groups'][u['chain']], core=chosen[n]['bounds'], cells=u['cells'],
        resources=dict(u['resources'])) for n, u in nodes.items() if u['chain']])
    from chain_guidance_verify import verify
    verify(root, out)
    from chain_guidance_plot import plots
    plots(out, core, device)
    for p, expected_hash in immutable.items():
        assert digest(p) == expected_hash, 'Input changed: ' + p
    for p, expected_hash in algorithm.items():
        assert digest(p) == expected_hash, 'Algorithm source changed: ' + p
    dump(out/'complete.json', dict(status='PASS', seconds=time.monotonic()-started,
        logical_modules=len(ids), physical_groups=len(physical['modules']), input_files_unchanged=True,
        files={str(p.relative_to(out)): digest(p) for p in out.rglob('*') if p.is_file()}))
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('partition_run', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--config', type=Path)
    args = parser.parse_args()
    run(args.partition_run, args.output, args.config)
