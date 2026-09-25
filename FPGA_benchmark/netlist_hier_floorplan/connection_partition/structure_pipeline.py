"""Optional cache-only experiment: contract, partition, expand, refine, evaluate."""
import argparse
from collections import Counter
import json
import math
import os
from pathlib import Path
import pickle
import shutil
import subprocess
import sys
import time

import partition as base
from structure_frontend import contract, cut_metrics, discover, expand, label_groups, operator_loss
from structure_refine import connectivity_metrics, refine

SOURCE = Path(__file__).resolve().parent


def load(path):
    return json.loads(Path(path).read_text())


def dump(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False)+'\n')


def timer(run, name, fn):
    started = time.monotonic()
    print(json.dumps(dict(stage=name, state='starting', time=time.time())), flush=True)
    result = fn()
    elapsed = time.monotonic()-started
    dump(run/(name+'.status.json'),dict(status='PASS',seconds=elapsed))
    print(json.dumps(dict(stage=name, state='complete', seconds=elapsed)), flush=True)
    return result


def branch_metrics(data, labels):
    raw = weighted = 0
    for _, d, ss, w in data['nets']:
        if not isinstance(d,int) or data['atom_of'][d]<0:
            continue
        source = labels[data['atom_of'][d]]
        pins = sum(source != labels[data['atom_of'][s]] for s in ss
                   if isinstance(s,int) and data['atom_of'][s]>=0)
        raw += pins
        weighted += pins*w
    return dict(cross_pins=raw,weighted_cross_pins=weighted/4)


def persist(run, name, data, groups, units, cores, baseline_labels, cfg, extra):
    from improve import save_candidate, objective, soft_edges
    from balanced_regions import local_fractions
    labels = label_groups(groups,len(data['atoms']))
    s = save_candidate(run/'balanced',name,data,groups,cores,baseline_labels,extra)
    baseline_cost = cut_metrics(data['edges'],baseline_labels)['weighted_km1']
    total = sum(w for _,w in data['edges'])/4
    metrics = s['metrics']
    metrics['logical_core_loss'] = objective(soft_edges(cores,cfg['core_soft_strength']),labels)[0]
    metrics['added_km1'] = metrics['weighted_km1']-baseline_cost
    metrics['global_added_fraction'] = metrics['added_km1']/total if total else 0.
    fractions = local_fractions(data,baseline_labels,labels)
    metrics['maximum_local_split_fraction'] = max((v['fraction'] for v in fractions.values()),default=0.)
    metrics.update(operator_loss(data,labels,units),**branch_metrics(data,labels))
    s['local_connection_constraints'] = fractions
    s['connectivity'] = connectivity_metrics(data,labels)
    dump(run/'balanced/candidates'/name/'summary.json',s)
    return s


def generate(run):
    if load(run/'source/balanced_config.json').get('partition_objective') == 'resource_logic_v1':
        from resource_pipeline import generate as resource_generate
        return resource_generate(run)
    cfg = load(run/'source/structure_config.json')
    physical_cfg = load(run/'source/balanced_config.json')
    old = Path(load(run/'request.json')['source_run'])
    data = timer(run,'load_graph',lambda:pickle.load((run/'graph.pkl').open('rb')))
    units,audit = timer(run,'operator_validation',lambda:discover(data,cfg))
    dump(run/'operator_validation.json',audit)
    with (run/'operators.pkl').open('wb') as f:
        pickle.dump(units,f,protocol=5)
    coarse,mapping,stats = timer(run,'contraction',lambda:contract(data,units))
    stats.update(accepted_operators=len(units), proposed_operators=len(audit),
                 rejected_reasons=dict(Counter(r for u in audit for r in u['rejection_reasons'])))
    dump(run/'contraction.json',stats)
    coarse_run=run/'coarse'
    coarse_run.mkdir()
    (coarse_run/'source').symlink_to(run/'source')
    with (coarse_run/'graph.pkl').open('wb') as f:
        pickle.dump(coarse,f,protocol=5)
    with (run/'expansion_map.pkl').open('wb') as f:
        pickle.dump(mapping,f,protocol=5)
    generated=[]
    k=max(cfg['bootstrap_k'],math.floor(sum(map(len,coarse['atoms']))/cfg['bootstrap_cell_cap'])+1)
    for seed in cfg['seeds']:
        timer(run,f'kahypar_s{seed}',lambda seed=seed:base.partition(coarse_run,k,cfg['bootstrap_cell_cap'],seed))
        parent=load(coarse_run/f'result_k{k}_s{seed}/partition.json')['groups']
        candidates=[('initial',parent)]
        split=[]
        t=time.monotonic()
        weights=list(map(len,coarse['atoms']))
        for i,aa in enumerate(parent):
            upper=math.ceil(cfg['split_max_parent_fraction']*sum(weights[a] for a in aa))
            if len(aa)<2 or max(weights[a] for a in aa)>upper:
                split.append(aa)
            else:
                split.extend(base.run_kahypar(coarse_run,coarse,aa,2,[upper]*2,weights,
                                             f'split_s{seed}_p{i}',seed))
        dump(run/f'split_s{seed}.status.json',dict(seconds=time.monotonic()-t,status='PASS'))
        candidates.append(('split',split))
        for kind,gg in candidates:
            name=f'front_s{seed}_{kind}'
            fine=expand(gg,mapping,len(data['atoms']))
            expected=cut_metrics(coarse['edges'],label_groups(gg,len(coarse['atoms'])))
            metrics=cut_metrics(data['edges'],label_groups(fine,len(data['atoms'])))
            assert expected==metrics
            folder=run/'generated'/name
            folder.mkdir(parents=True)
            dump(folder/'groups.json',fine)
            record=dict(name=name,seed=seed,kind=kind,modules=len(fine),**metrics,
                        **operator_loss(data,label_groups(fine,len(data['atoms'])),units))
            assert record['split_operators']==0
            generated.append(record)
    dump(run/'generation.json',dict(candidates=generated,contraction=stats,
                                   quotient_cut_validation='PASS',membership_and_resources='PASS'))


def evaluate(run):
    if load(run/'source/balanced_config.json').get('partition_objective') == 'resource_logic_v1':
        from resource_pipeline import evaluate as resource_evaluate
        return resource_evaluate(run)
    from improve import digest
    from balanced_regions import evaluate as region_evaluate
    from balanced_deliver import rank, deliver
    old=Path(load(run/'request.json')['source_run'])
    cfg=load(run/'source/structure_config.json')
    pcfg=load(run/'source/balanced_config.json')
    reuse=load(run/'reused_candidates.json') if (run/'reused_candidates.json').exists() else None
    if reuse:
        assert reuse['graph_sha256']==digest(run/'graph.pkl')
        assert reuse['config_sha256']==digest(run/'source/balanced_config.json')
    data=pickle.load((run/'graph.pkl').open('rb'))
    units=pickle.load((run/'operators.pkl').open('rb'))
    cores=load(old/'balanced/cores.json')
    baseline_groups=load(old/'balanced/candidates/baseline5/groups.json')
    baseline_labels=label_groups(baseline_groups,len(data['atoms']))
    selected=load(old/'balanced/selection.json')['selected']
    reference=load(old/'balanced/candidates'/selected/'groups.json')
    persist(run,'control_current',data,reference,units,cores,baseline_labels,pcfg,
            dict(kind='unchanged_current_partition',source=str(old)))
    previous_cfg=load(old/'planning_source/balanced_config.json')
    if pcfg.get('hypernet_model','all_atom_v1') == previous_cfg.get('hypernet_model','all_atom_v1'):
        shutil.copy2(old/'balanced/candidates'/selected/'balanced_regions.json',
                     run/'balanced/candidates/control_current/balanced_regions.json')
    else:
        # Never rank a legacy-D control against candidates scored with new D.
        timer(run,'control_resource_regions',lambda:region_evaluate(run/'balanced',['control_current']))
    names=[]
    proposals=[('current_refined',reference,True),('current_operator_only',reference,False)]
    generated=load(run/'generation.json')['candidates']
    for kind in ['initial','split']:
        best=min((r for r in generated if r['kind']==kind),
                 key=lambda r:(r['weighted_km1'],r['weighted_cut'],r['seed']))
        groups=load(run/'generated'/best['name']/'groups.json')
        proposals.append((best['name']+'_refined',groups,True))
        if kind=='split':
            proposals.append((best['name']+'_unmodified',groups,None))
    if len(proposals)>cfg['max_region_candidates']:
        raise ValueError('Region budget must retain both before/after refinement candidates.')
    for name,groups,move_components in proposals:
        # Imported evaluations are reusable only through an explicitly verified
        # experiment continuation, never by changing the original input cache.
        if (run/'balanced/candidates'/name/'summary.json').exists():
            if not reuse or name not in reuse['candidates']:
                raise ValueError('Existing candidate has no verified continuation manifest: '+name)
            for relative,h in reuse['candidates'][name].items():
                assert digest(run/'balanced/candidates'/name/relative)==h
            names.append(name)
            continue
        if move_components is None:
            persist(run,name,data,groups,units,cores,baseline_labels,pcfg,
                    dict(kind='before_local_refinement',reason='Retain a physical-score fallback.'))
            names.append(name)
            continue
        local_cfg=dict(cfg,move_components=move_components)
        revised,detail=timer(run,name,lambda groups=groups:refine(data,groups,units,local_cfg))
        dump(run/(name+'.refinement.json'),detail)
        persist(run,name,data,revised,units,cores,baseline_labels,pcfg,
                dict(kind='structured_local_refinement',move_components=move_components,
                     details=str(run/(name+'.refinement.json'))))
        names.append(name)
    timer(run,'resource_regions',lambda:region_evaluate(run/'balanced',names))
    winner,rows=rank(run/'balanced',pcfg)
    assert winner is not None
    dump(run/'balanced/comparison.json',rows)
    dump(run/'balanced/selection.json',dict(selected=winner['candidate'],metrics=winner,
        rule='Unchanged balanced score/budgets and 1% tie rule. Original current partition retained.',
        scope='Best among bounded evaluated proposals, not a global or routed optimum.'))
    timer(run,'delivery',lambda:deliver(run/'balanced',winner['candidate'],id_prefix='S'))
    assert digest(run/'graph.pkl')==load(run/'balanced/binding.json')['graph_sha256']
    dump(run/'partition_complete.json',dict(selected=winner['candidate'],evaluated=names,
        graph_unchanged=True,
        baseline_labels_unchanged=True,frontend_candidates=generated,selected_metrics=winner))


def setup(output, previous):
    from improve import digest
    output.mkdir(parents=True,exist_ok=False)
    shutil.copytree(SOURCE,output/'source',ignore=shutil.ignore_patterns('__pycache__'))
    adapter=SOURCE.parent/'balanced_implementation/adapter.tcl'
    if not adapter.exists():
        adapter=SOURCE/'adapter_reference.tcl'
    shutil.copy2(adapter,output/'source/adapter_reference.tcl')
    # Freeze the existing GETRF comparison settings, not unrelated later defaults.
    for name in ['balanced_config.json','directed_config.json','static_regions.py']:
        shutil.copy2(previous/'planning_source'/name,output/'source'/name)
    for name in ['balanced_config.json','directed_config.json']:
        frozen=load(output/'source'/name)
        current=load(SOURCE/name)
        keys=['hypernet_model','boundary_frontier_max_entries']
        if name=='balanced_config.json':
            keys += ['partition_objective','cut_weight','logical_core_weight','core_soft_strength',
                     'module_cost_fraction_of_all_net_weight','selection_relative_tolerance']
        for key in keys:
            if key in current:
                frozen[key]=current[key]
        dump(output/'source'/name,frozen)
    dump(output/'request.json',dict(source_run=str(previous),placement_and_route=False,
        floorplan_beta=1,partition_objective=load(output/'source/balanced_config.json').get('partition_objective','legacy'),
        scope='Reversible operator frontend, resource-constrained partition, then independent fixed-membership floorplan.'))
    (output/'graph.pkl').symlink_to(previous/'graph.pkl')
    shutil.copy2(previous/'cr.tsv',output/'cr.tsv')
    balanced=output/'balanced'
    balanced.mkdir()
    for name,target in [('source',output/'source'),('graph.pkl',previous/'graph.pkl'),('baseline',previous/'baseline')]:
        (balanced/name).symlink_to(target)
    shutil.copy2(previous/'cr.tsv',balanced/'cr.tsv')
    shutil.copy2(previous/'balanced/cores.json',balanced/'cores.json')
    folder=balanced/'candidates/baseline5'
    folder.mkdir(parents=True)
    shutil.copy2(previous/'balanced/candidates/baseline5/groups.json',folder/'groups.json')
    binding=load(previous/'balanced/binding.json')
    assert digest(previous/'graph.pkl')==binding['graph_sha256']
    binding['config_sha256']=digest(output/'source/balanced_config.json')
    dump(balanced/'binding.json',binding)
    dump(output/'source_manifest.json',{p.name:digest(p) for p in (output/'source').iterdir() if p.is_file()})


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['run','partition','generate','evaluate','floorplan'])
    parser.add_argument('output',type=Path)
    parser.add_argument('--from-run',type=Path)
    parser.add_argument('--kahypar-python',default='/usr/bin/python3')
    parser.add_argument('--kahypar-path')
    args=parser.parse_args()
    run=args.output.resolve()
    if args.action=='generate':
        generate(run)
    elif args.action=='evaluate':
        evaluate(run)
    elif args.action=='floorplan':
        from structure_floorplan import finish
        finish(run)
    else:
        start=time.monotonic()
        if args.from_run is None:
            parser.error('--from-run is required for run')
        setup(run,args.from_run.resolve())
        request=load(run/'request.json')
        request.update(floorplan_requested=args.action=='run',
                       scope='Partition only; no floorplan or placement/route.' if args.action=='partition'
                       else request['scope'])
        dump(run/'request.json',request)
        # Parent owns NumPy/Gurobi; the tested KaHyPar binding uses a separate runtime.
        env=dict(os.environ,OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1')
        if args.kahypar_path:
            env['PYTHONPATH']=args.kahypar_path
        # Candidate summaries/evaluation import NumPy; generation stays stdlib-only.
        with (run/'generation.log').open('w') as log:
            timer(run,'generation',lambda:subprocess.run([args.kahypar_python,'-B','-u',
                str(run/'source/structure_pipeline.py'),'generate',str(run)],env=env,
                stdout=log,stderr=subprocess.STDOUT,check=True))
        for action in (['evaluate'] if args.action=='partition' else ['evaluate','floorplan']):
            with (run/(action+'.log')).open('w') as log:
                timer(run,action,lambda action=action:subprocess.run([sys.executable,'-B','-u',
                    str(run/'source/structure_pipeline.py'),action,str(run)],
                    stdout=log,stderr=subprocess.STDOUT,check=True))
        dump(run/'complete.json',dict(status='PASS',selected=load(run/'partition_complete.json')['selected'],
            seconds=time.monotonic()-start,placement_and_route=False,
            floorplan_requested=args.action=='run',
            floorplan_objective=load(run/'floorplan/solution.json')['objective'] if args.action=='run' else None))


if __name__=='__main__':main()
