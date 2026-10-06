"""One complete directed refinement pass over a verified existing cache.

Reuse the selected partition, candidates, original graph and protection bundle.
No discovery, KaHyPar generation, physical model or backend stage is executed.
"""
import argparse
import json
import pickle
from pathlib import Path
import time

from directed_units import SCHEMA, refine
from improve import digest
from joint_units import load_protection, require_intact
from resource_partition import Budget, profile_from_cr_table, score
from structure_frontend import label_groups
from structure_pipeline import dump, load, persist, setup


def read_candidates(run, cache, data):
    """Validate provenance before deserializing or reusing structural candidates."""
    binding = load(cache/'binding.json')
    graph_sha = digest(run/'graph.pkl')
    reference = load(run/'balanced/baseline/final/modules.json')
    if (binding['schema'] != SCHEMA or binding['graph_sha256'] != graph_sha or
            load(run/'balanced/binding.json')['graph_sha256'] != graph_sha or
            binding['input_sha256'] != reference['input_sha256']):
        raise ValueError('Candidate graph/DCP binding mismatch')
    protection_sha = digest(run/'protection_manifest.json') if (run/'protection_manifest.json').exists() else None
    if binding.get('protection_manifest_sha256') != protection_sha:
        raise ValueError('Candidate protection binding mismatch')
    load_protection(run)
    if digest(cache/'candidates.pkl') != binding['candidate_sha256']:
        raise ValueError('Candidate payload hash mismatch')
    macro = binding.get('macro_binding')
    if macro and (macro['graph_sha256'] != graph_sha or
            macro['input_sha256'] != reference['input_sha256'] or
            digest(run/'macro_timing/macro_timing.pkl') != macro['payload_sha256']):
        raise ValueError('Candidate macro binding mismatch')
    audit = load(cache/'discovery.json')
    if audit['schema'] != SCHEMA or audit['options'] != binding['options']:
        raise ValueError('Candidate discovery options mismatch')
    with (cache/'candidates.pkl').open('rb') as stream:
        rows = pickle.load(stream)
    if len(rows) != audit['candidates'] or len({r['id'] for r in rows}) != len(rows):
        raise ValueError('Candidate count or ID mismatch')
    for row in rows:
        atoms, anchors = row['atoms'], row['anchors']
        if (not atoms or len(set(atoms)) != len(atoms) or len(set(anchors)) != len(anchors) or
                set(atoms).intersection(anchors) or any(type(a) is not int or
                not 0 <= a < len(data['atoms']) for a in atoms+anchors)):
            raise ValueError('Invalid cached candidate atoms')
    return rows, binding


def run_complete(previous, cache, run, max_accepted_moves=64):
    started = time.monotonic()
    old_selection = load(previous/'balanced/selection.json')['selected']
    source_paths = ['graph.pkl', 'cr.tsv', 'balanced/cores.json', 'balanced/selection.json',
        'balanced/candidates/'+old_selection+'/groups.json',
        'source/balanced_config.json', 'source/resource_partition_config.json',
        'source/structure_config.json', 'protection_manifest.json', 'protection_units.pkl',
        'joint_chains.pkl', 'operators.pkl', 'joint_discovery.json']
    source_hashes = {p:digest(previous/p) for p in source_paths}
    cache_hashes = {p:digest(cache/p) for p in ['binding.json','discovery.json','candidates.pkl']}
    setup(run, previous, preserve_partition_settings=True)
    for name in ['operators.pkl','joint_chains.pkl','protection_units.pkl','joint_discovery.json',
                 'protection_manifest.json','resource_profile.json','contraction.json',
                 'generation.json','generated','macro_timing']:
        if (previous/name).exists():
            (run/name).symlink_to((previous/name).resolve(), target_is_directory=(previous/name).is_dir())
    (run/'directed_units').symlink_to(cache, target_is_directory=True)
    dump(run/'request.json',dict(source_run=str(previous), source_candidate=old_selection,
        candidate_cache=str(cache), action='cached_directed_complete_pass',
        complete_pass=True, passes=1, time_limit_seconds=None,
        evaluation_limit='candidate_count * input_module_count (finite bound)',
        accepted_move_limit=max_accepted_moves,
        after_acceptance_limit='Continue evaluation without changing partition; record improving proposals.',
        kahypar_executed=False, discovery_executed=False, floorplan_requested=False,
        placement_and_route=False, scope='Complete current target-neighborhood traversal, not repeated convergence.'))
    dump(run/'cache_input_hashes.json',dict(source_run=source_hashes,candidate_cache=cache_hashes))
    with (run/'graph.pkl').open('rb') as stream:
        data = pickle.load(stream)
    candidates, binding = read_candidates(run, cache, data)
    protected, joint, _ = load_protection(run)
    with (run/'operators.pkl').open('rb') as stream:
        operators = pickle.load(stream)
    groups = load(previous/'balanced/candidates'/old_selection/'groups.json')
    pcfg = load(run/'source/balanced_config.json')
    rcfg = load(run/'source/resource_partition_config.json')
    budget = Budget(profile_from_cr_table(run/'cr.tsv',rcfg['resource_ratios']))
    if budget.profile != load(run/'resource_profile.json'):
        raise ValueError('Changed resource profile')
    cores = load(run/'balanced/cores.json')

    def progress(row):
        row.update(stage='complete_directed_pass',time=time.time())
        tmp = run/'progress.tmp.json'
        dump(tmp,row)
        tmp.replace(run/'progress.json')
        with (run/'progress.jsonl').open('a') as stream:
            stream.write(json.dumps(row)+'\n')
        print(json.dumps(row),flush=True)

    revised, detail = refine(data,groups,candidates,cores,protected,budget,pcfg,
        rcfg['merge_affinity_threshold'],cfg=binding['options'],complete_pass=True,progress=progress,
        max_moves=max_accepted_moves)
    dump(run/'complete_pass_refinement.json',detail)
    if not detail['all_candidates_completed']:
        raise AssertionError('Complete traversal was requested but not achieved')
    baseline = load(run/'balanced/candidates/baseline5/groups.json')
    baseline_labels = label_groups(baseline,len(data['atoms']))
    from balanced_physical import admissible
    from resource_pipeline import rank
    from balanced_deliver import deliver

    def save(name, proposal, kind):
        labels = label_groups(proposal,len(data['atoms']))
        protection = require_intact(labels,protected,'cached refinement candidate')
        summary = persist(run,name,data,proposal,operators,cores,baseline_labels,pcfg,
                          dict(kind=kind,partition_objective='resource_logic_v1'))
        summary['metrics'].pop('near_cell_cap_count',None)
        summary['protection'] = protection
        audit = budget.audit(data,proposal,rcfg['soft_min_crs'])
        for module,row in zip(summary['modules'],audit['modules']):
            module.update(equivalent_crs=row['equivalent_crs'],below_soft_minimum=row['below_soft_minimum'],
                          has_inter_module_connections=module['floorplan_eligible'],floorplan_eligible=True)
        folder = run/'balanced/candidates'/name
        dump(folder/'summary.json',summary)
        dump(folder/'resource_evaluation.json',dict(schema='resource_logic_v1',
            status='resource_feasible' if audit['valid'] else 'resource_infeasible',audit=audit,
            score=score(summary['metrics'],pcfg),protection=protection,aggregation_eligible=True,
            admissible=admissible(summary['metrics'],pcfg),positions_assigned=False))
        return summary

    save('control_current',groups,'unchanged_current_partition')
    summary = save('cached_full_pass',revised,'cached_directed_complete_pass')
    for key in ['weighted_km1','logical_core_loss']:
        if abs(summary['metrics'][key]-detail['after'][key]) > 1e-7:
            raise AssertionError('Independent final score mismatch: '+key)
    old_labels = label_groups(groups,len(data['atoms']))
    replay = old_labels.copy()
    for move in detail['moves']:
        for atom in move['atoms']:
            replay[atom] = move['target']
    replay_groups = {}
    for atom,label in enumerate(replay):
        replay_groups.setdefault(label,[]).append(atom)
    if {frozenset(g) for g in replay_groups.values()} != {frozenset(g) for g in revised}:
        raise AssertionError('Move history does not reproduce final partition')
    moved = [a for a,(before,after) in enumerate(zip(old_labels,replay)) if before != after]
    winner, rows = rank(run/'balanced',pcfg)
    if winner is None:
        raise ValueError('No candidate passed original resource/protection/communication constraints')
    dump(run/'balanced/comparison.json',rows)
    dump(run/'balanced/selection.json',dict(selected=winner['candidate'],metrics=winner,
        rule='Exact unchanged C+L and communication admission, with current partition as fallback.'))
    deliver(run/'balanced',winner['candidate'],id_prefix='S')
    if (any(digest(previous/p) != h for p,h in source_hashes.items()) or
            any(digest(cache/p) != h for p,h in cache_hashes.items())):
        raise AssertionError('Source partition or candidate cache changed')
    result = dict(status='PASS',selected=winner['candidate'],source_candidate=old_selection,
        before=detail['before'],after=detail['after'],accepted_moves=len(detail['moves']),
        deferred_improvements=len(detail['deferred_improvements']),
        acceptance_limit=max_accepted_moves,acceptance_limit_reached=detail['acceptance_limit_reached'],
        moved_atoms=len(moved),moved_cells=sum(len(data['atoms'][a]) for a in moved),
        candidates_total=len(candidates),candidates_completed=detail['candidates_completed'],
        evaluations=detail['evaluations'],stop_reason=detail['stop_reason'],
        source_inputs_unchanged=True,graph_unchanged=True,protection='PASS',
        protected_joint_chains=len(joint),positions_assigned=False,
        kahypar_executed=False,discovery_executed=False,floorplan_requested=False,
        placement_and_route=False,seconds=time.monotonic()-started)
    dump(run/'partition_complete.json',result)
    dump(run/'complete.json',result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--from-run',required=True,type=Path)
    parser.add_argument('--candidate-cache',type=Path)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--max-accepted-moves',type=int,default=64)
    args = parser.parse_args()
    previous = args.from_run.resolve()
    result = run_complete(previous,(args.candidate_cache or previous/'directed_units').resolve(),
                          args.output.resolve(),args.max_accepted_moves)
    print(json.dumps(result),flush=True)
