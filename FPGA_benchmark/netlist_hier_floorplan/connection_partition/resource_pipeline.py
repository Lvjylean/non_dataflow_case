"""Cache-only resource/logic partition; physical models start after selection."""
from collections import Counter
import json
import pickle
from pathlib import Path

import partition as base
from resource_partition import (SCHEMA, Budget, profile_from_cr_table, recursive_groups,
                                selective_merge, projected_core_edges, rank_rows, score)
from structure_frontend import contract, discover, expand, label_groups, cut_metrics
from structure_pipeline import load, dump, timer, persist
from joint_discovery import discover_joint
from joint_units import integrity, require_intact, protection_units, load_protection


def load_pickle(path):
    with path.open('rb') as stream:return pickle.load(stream)


def generate(run):
    cfg=load(run/'source/structure_config.json')
    pcfg=load(run/'source/balanced_config.json')
    rcfg=load(run/'source/resource_partition_config.json')
    profile=profile_from_cr_table(run/'cr.tsv',rcfg['resource_ratios'])
    dump(run/'resource_profile.json',profile)
    budget=Budget(profile)
    data=timer(run,'load_graph',lambda:load_pickle(run/'graph.pkl'))
    units,audit=timer(run,'operator_validation',lambda:discover(data,cfg))
    oversized={u['hierarchy'] for u in units if not budget.fits(u['resources'])}
    # Logical protection is optional; an over-budget operator must remain splittable.
    units=[u for u in units if u['hierarchy'] not in oversized]
    for row in audit:
        if row['hierarchy'] in oversized:
            row['accepted']=False
            row['rejection_reasons'].append('exceeds_single_die_resource_budget')
    dump(run/'operator_validation.json',audit)
    with (run/'operators.pkl').open('wb') as stream:pickle.dump(units,stream,protocol=5)
    joint,chain_audit=timer(run,'joint_chain_discovery',lambda:discover_joint(
        data,units,rcfg.get('joint_chains',dict(enabled=False)),budget.fits))
    protected=protection_units(units,joint)
    dump(run/'joint_discovery.json',chain_audit)
    for name, value in [('joint_chains.pkl',joint),('protection_units.pkl',protected)]:
        with (run/name).open('wb') as stream:pickle.dump(value,stream,protocol=5)
    from improve import digest
    dump(run/'protection_manifest.json',dict(schema='local_joint_chains_v1',
        atom_count=len(data['atoms']),operator_count=len(units),joint_chains=len(joint),
        files={name:digest(run/name) for name in ['graph.pkl','operators.pkl','joint_chains.pkl',
            'protection_units.pkl','joint_discovery.json','source/resource_partition_config.json',
            'source/structure_config.json']}))
    coarse,mapping,stats=timer(run,'contraction',lambda:contract(data,protected))
    stats.update(accepted_operators=len(units),proposed_operators=len(audit),
                 accepted_joint_chains=len(joint),protected_units=len(protected),
                 resource_rejected_operators=sorted(oversized))
    dump(run/'contraction.json',stats)
    with (run/'expansion_map.pkl').open('wb') as stream:pickle.dump(mapping,stream,protocol=5)
    cores=load(run/'balanced/cores.json')
    proposal=dict(coarse,edges=coarse['edges']+projected_core_edges(cores,mapping,pcfg))
    coarse_run=run/'coarse';coarse_run.mkdir()
    (coarse_run/'source').symlink_to(run/'source')
    generated=[]
    for seed in cfg['seeds']:
        for target in rcfg['initial_target_crs']:
            name=f'resource_s{seed}_cr{target:g}'
            groups,detail=timer(run,name,lambda:recursive_groups(coarse_run,proposal,budget,target,seed,
                fraction=cfg['split_max_parent_fraction'],max_calls=rcfg['max_split_calls_per_candidate']))
            fine=expand(groups,mapping,len(data['atoms']))
            require_intact(label_groups(fine,len(data['atoms'])),protected,'KaHyPar expansion')
            assert cut_metrics(coarse['edges'],label_groups(groups,len(mapping))) == cut_metrics(
                data['edges'],label_groups(fine,len(data['atoms'])))
            fine,merges=timer(run,name+'_merge',lambda:selective_merge(data,fine,budget,
                threshold=rcfg['merge_affinity_threshold'],soft_min=rcfg['soft_min_crs']))
            protection=require_intact(label_groups(fine,len(data['atoms'])),protected,'selective merging')
            folder=run/'generated'/name;folder.mkdir(parents=True)
            dump(folder/'groups.json',fine)
            dump(folder/'generation_detail.json',dict(splits=detail,merges=merges))
            generated.append(dict(name=name,seed=seed,initial_target_crs=target,modules=len(fine),
                protection=protection,
                **cut_metrics(data['edges'],label_groups(fine,len(data['atoms'])))))
    dump(run/'generation.json',dict(schema=SCHEMA,candidates=generated,contraction=stats,
        quotient_cut_validation='PASS',membership_and_resources='PASS',positions_assigned=False,
        objective='cut_weight*C + logical_core_weight*L',cell_cap=None,fixed_k=None))


def evaluate(run):
    from improve import digest
    from structure_refine import refine
    from balanced_physical import admissible
    from balanced_deliver import rank, deliver
    old=Path(load(run/'request.json')['source_run'])
    cfg=load(run/'source/structure_config.json')
    pcfg=load(run/'source/balanced_config.json')
    rcfg=load(run/'source/resource_partition_config.json')
    expected=profile_from_cr_table(run/'cr.tsv',rcfg['resource_ratios'])
    if expected != load(run/'resource_profile.json'):
        raise ValueError('Resource profile changed after generation; start a new run.')
    budget=Budget(expected)
    data=load_pickle(run/'graph.pkl')
    units=load_pickle(run/'operators.pkl')
    protected,joint,manifest=load_protection(run)
    cores=load(run/'balanced/cores.json')
    baseline=load(run/'balanced/candidates/baseline5/groups.json')
    baseline_labels=label_groups(baseline,len(data['atoms']))
    selected=load(old/'balanced/selection.json')['selected']
    reference=load(old/'balanced/candidates'/selected/'groups.json')
    generated=load(run/'generation.json')['candidates']

    def save(name,groups,kind,extra=None):
        protection=integrity(label_groups(groups,len(data['atoms'])),protected)
        if kind!='unchanged_current_partition' and not protection['valid']:
            raise ValueError('Candidate splits a protected unit: '+name)
        summary=persist(run,name,data,groups,units,cores,baseline_labels,pcfg,
                        dict(kind=kind,partition_objective=SCHEMA,**(extra or {})))
        summary['metrics'].pop('near_cell_cap_count',None)
        summary['protection']=protection
        audit=budget.audit(data,groups,rcfg['soft_min_crs'])
        for module,row in zip(summary['modules'],audit['modules']):
            module.update(equivalent_crs=row['equivalent_crs'],
                          below_soft_minimum=row['below_soft_minimum'])
            # Isolated logic remains a real module; connectivity is diagnostic,
            # not a reason to omit its resources/membership from floorplanning.
            module['has_inter_module_connections']=module['floorplan_eligible']
            module['floorplan_eligible']=True
        folder=run/'balanced/candidates'/name
        dump(folder/'summary.json',summary)
        dump(folder/'resource_evaluation.json',dict(schema=SCHEMA,
            status='resource_feasible' if audit['valid'] else 'resource_infeasible',
            audit=audit,score=score(summary['metrics'],pcfg),
            protection=protection,
            admissible=admissible(summary['metrics'],pcfg),positions_assigned=False))

    save('control_current',reference,'unchanged_current_partition',dict(source=str(old)))
    proposals=[(r['name'],load(run/'generated'/r['name']/'groups.json')) for r in generated]
    reference_protection=integrity(label_groups(reference,len(data['atoms'])),protected)
    dump(run/'historical_candidate_admission.json',dict(source=str(old),protection=reference_protection,
        eligible=reference_protection['valid'] and budget.audit(data,reference)['valid']))
    if budget.audit(data,reference)['valid'] and reference_protection['valid']:
        proposals.append(('control_candidate',reference))
    for name,groups in proposals:
        # Keep both stages: local pin-cut repair need not decrease logical loss.
        save(name,groups,'before_local_refinement')
        revised,detail=timer(run,name+'_refine',lambda:refine(data,groups,protected,
            dict(cfg,require_intact_units=True),resource_fits=budget.fits))
        revised,merges=selective_merge(data,revised,budget,
            threshold=rcfg['merge_affinity_threshold'],soft_min=rcfg['soft_min_crs'],only_small=True)
        dump(run/(name+'.refinement.json'),dict(refinement=detail,small_merges=merges))
        save(name+'_refined',revised,'structured_local_refinement')
    winner,rows=rank(run/'balanced',pcfg)
    dump(run/'balanced/comparison.json',rows)
    if winner is None:
        dump(run/'partition_complete.json',dict(status='no_admissible_candidate',schema=SCHEMA,
            reason='No candidate passed both resource limits and existing connection budgets; neither relaxed.',
            physical_feasibility_proven=False))
        raise ValueError('No resource-feasible candidate within connection budgets; see balanced/comparison.json.')
    dump(run/'balanced/selection.json',dict(selected=winner['candidate'],metrics=winner,
        rule=f"Exact {pcfg['cut_weight']:g}C+{pcfg['logical_core_weight']:g}L; no D, no count penalty or count tie-break.",
        scope='Best among bounded proposals under resource and connection constraints; not a physical placement certificate.'))
    timer(run,'delivery',lambda:deliver(run/'balanced',winner['candidate'],id_prefix='S'))
    assert digest(run/'graph.pkl')==load(run/'balanced/binding.json')['graph_sha256']
    dump(run/'partition_complete.json',dict(status='PASS',schema=SCHEMA,selected=winner['candidate'],
        selected_metrics=winner,graph_unchanged=True,positions_assigned=False,
        protected_joint_chains=len(joint),protection='PASS',
        physical_feasibility_proven=False,frontend_candidates=generated))


def rank(run,cfg,multiplier=1):
    from balanced_physical import admissible
    rows=[]
    protected,_,manifest=load_protection(run.parent)
    for path in sorted((run/'candidates').glob('*/resource_evaluation.json')):
        result=load(path)
        if result['schema']!=SCHEMA:
            raise ValueError('Partition objective schema mismatch: '+str(path))
        metrics=load(path.parent/'summary.json')['metrics']
        protection=(integrity(label_groups(load(path.parent/'groups.json'),manifest['atom_count']),protected)
                    if manifest else dict(valid=True,split_units=0))
        rows.append(dict(metrics,candidate=path.parent.name,score=score(metrics,cfg),
            resource_feasible=result['audit']['valid'],admissible=admissible(metrics,cfg,multiplier),
            protection_feasible=protection['valid'],split_protected_units=protection['split_units'],
            positions_assigned=False,physical_feasibility_proven=False))
    return rank_rows(rows,cfg),rows
