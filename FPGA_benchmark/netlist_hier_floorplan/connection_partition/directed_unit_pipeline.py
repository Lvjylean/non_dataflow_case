"""Frozen-cache directed-unit preparation and isolated partition validation."""
import argparse
import json
from pathlib import Path
import pickle
import time

from directed_units import SCHEMA, build_topology, discover, options, refine
from improve import digest
from joint_units import load_protection, require_intact
from macro_timing import read as read_macro
from resource_partition import Budget, profile_from_cr_table
from structure_frontend import label_groups


def load(path):
    return json.loads(path.read_text())


def dump(path, value):
    path.write_text(json.dumps(value, indent=2)+'\n')


def prepare(run, data, protected, macro_path, output, cfg=None):
    """Hash-bound original inputs; never silently reuse a discovery cache."""
    cfg = options(cfg)
    graph_sha = digest(run/'graph.pkl')
    binding = load(run/'balanced/binding.json')
    if binding['graph_sha256'] != graph_sha:
        raise ValueError('Partition graph binding mismatch')
    source = load(run/'balanced/baseline/final/modules.json')
    macro = read_macro(macro_path, graph_sha, source['input_sha256']) if macro_path else None
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    graph = build_topology(data, macro)
    topology_seconds = time.monotonic()-started
    started = time.monotonic()
    rows, audit = discover(data, graph, protected, cfg)
    audit.update(topology_seconds=topology_seconds, discovery_seconds=time.monotonic()-started)
    with (output/'candidates.pkl').open('wb') as stream:
        pickle.dump(rows, stream, protocol=5)
    dump(output/'discovery.json', audit)
    dump(output/'binding.json', dict(schema=SCHEMA, graph_sha256=graph_sha,
        input_sha256=source['input_sha256'], options=cfg,
        candidate_sha256=digest(output/'candidates.pkl'),
        protection_manifest_sha256=digest(run/'protection_manifest.json')
            if (run/'protection_manifest.json').exists() else None,
        macro_binding=macro.get('binding') if macro else None))
    return rows, audit


def validate(run, macro_path, output, cfg=None, seconds=None):
    """One bounded original-netlist trial; no floorplan, native STA or P&R."""
    output.mkdir(parents=True, exist_ok=False)
    source_candidate=load(run/'balanced/selection.json')['selected']
    input_paths=['graph.pkl','cr.tsv','balanced/cores.json','balanced/selection.json',
        'source/balanced_config.json','source/resource_partition_config.json','source/structure_config.json',
        'balanced/candidates/'+source_candidate+'/groups.json','balanced/candidates/baseline5/groups.json']
    if (run/'protection_manifest.json').exists():
        input_paths += ['protection_manifest.json','protection_units.pkl','joint_chains.pkl']
    input_hashes={name:digest(run/name) for name in input_paths}
    with (run/'graph.pkl').open('rb') as stream:
        data = pickle.load(stream)
    protected, joint, _ = load_protection(run)
    rows, audit = prepare(run, data, protected, macro_path, output/'discovery', cfg)
    pcfg = load(run/'source/balanced_config.json')
    rcfg = load(run/'source/resource_partition_config.json')
    scfg = load(run/'source/structure_config.json')
    budget = Budget(profile_from_cr_table(run/'cr.tsv', rcfg['resource_ratios']))
    cores = load(run/'balanced/cores.json')
    selected = load(run/'balanced/selection.json')['selected']
    groups = load(run/'balanced/candidates'/selected/'groups.json')
    revised, detail = refine(data, groups, rows, cores, protected, budget, pcfg,
        rcfg['merge_affinity_threshold'], seconds=scfg['local_search_seconds'] if seconds is None else seconds,
        max_moves=scfg['local_max_moves'], cfg=cfg)
    dump(output/'groups.json', revised)
    dump(output/'refinement.json', detail)
    # Reuse the production communication-budget and membership evaluator.
    from structure_pipeline import persist
    from balanced_physical import admissible
    baseline = load(run/'balanced/candidates/baseline5/groups.json')
    summary = persist(output, 'directed_trial', data, revised, protected, cores,
        label_groups(baseline, len(data['atoms'])), pcfg, dict(kind=SCHEMA))
    admission = admissible(summary['metrics'], pcfg)
    labels = label_groups(revised, len(data['atoms']))
    # Module IDs may be compacted/reordered; compare partitions by atom sets.
    old_sets = {frozenset(g) for g in groups}
    new_sets = {frozenset(g) for g in revised}
    old_labels=label_groups(groups,len(data['atoms']))
    replay=old_labels.copy()
    for move in detail['moves']:
        for a in move['atoms']:replay[a]=move['target']
    moved=[a for a,(old,new) in enumerate(zip(old_labels,replay)) if old!=new]
    for key in ('weighted_km1', 'logical_core_loss'):
        if abs(summary['metrics'][key]-detail['after'][key]) > 1e-7:
            raise AssertionError('Independent candidate metric mismatch: '+key)
    result = dict(status='PASS', schema=SCHEMA, source_run=str(run),
        source_candidate=selected, candidates=len(rows), modules_before=len(groups),
        modules_after=len(revised), partition_changed=old_sets != new_sets,
        moved_atoms=len(moved),moved_cells=sum(len(data['atoms'][a]) for a in moved),
        before=detail['before'], after=detail['after'], accepted_moves=len(detail['moves']),
        communication_admissible=admission,
        candidate_eligible=bool(admission and detail['after']['J'] < detail['before']['J']-1e-9),
        protection=require_intact(labels, protected, 'standalone final'),
        joint_chains=len(joint), resource_audit=budget.audit(data, revised),
        parameters=dict(resource_ratios=rcfg['resource_ratios'],
            merge_affinity_threshold=rcfg['merge_affinity_threshold'],
            cut_weight=pcfg['cut_weight'],logical_core_weight=pcfg['logical_core_weight'],
            core_soft_strength=pcfg['core_soft_strength']),
        source_inputs_unchanged=all(digest(run/name)==sha for name,sha in input_hashes.items()),
        floorplan_run=False, placement_and_route=False, baseline_replaced=False)
    if not result['source_inputs_unchanged']:
        raise AssertionError('Source cache input changed')
    dump(output/'input_hashes.json',input_hashes)
    dump(output/'summary.json', result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--from-run', type=Path, required=True)
    parser.add_argument('--macro-timing', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seconds', type=float)
    args = parser.parse_args()
    result = validate(args.from_run.resolve(), args.macro_timing, args.output.resolve(), seconds=args.seconds)
    print(json.dumps({k:result[k] for k in ('status','modules_before','modules_after','before','after',
                                         'accepted_moves','candidate_eligible')}), flush=True)
