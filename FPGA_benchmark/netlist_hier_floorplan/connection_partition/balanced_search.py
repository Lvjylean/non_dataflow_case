"""Compose, reverse-merge and refine proposals using one recorded evaluator."""
import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from improve import load_context, save_candidate, labels_for, objective, soft_edges, boundary_refine
from core_adjust import relocate_cores
from balanced_regions import local_fractions
from balanced_physical import admissible


def context(run):
    data,_,baseline,_=load_context(run)
    cfg=json.loads((run/'source/balanced_config.json').read_text())
    cores=json.loads((run/'cores.json').read_text())
    return data,baseline,cfg,cores


def persist(run,name,data,baseline,cfg,cores,groups,detail):
    signature=tuple(sorted(tuple(sorted(g)) for g in groups))
    for f in sorted((run/'candidates').glob('*/groups.json')):
        existing=json.loads(f.read_text())
        if tuple(sorted(tuple(sorted(g)) for g in existing))==signature:
            return f.parent.name
    labels=labels_for(data,groups)
    s=save_candidate(run,name,data,groups,cores,baseline['membership'],detail)
    metrics=s['metrics'];weight=sum(w for _,w in data['edges'])/4
    metrics['logical_core_loss']=objective(soft_edges(cores,cfg['core_soft_strength']),labels)[0]
    metrics['added_km1']=metrics['weighted_km1']-baseline['weighted_km1']
    metrics['global_added_fraction']=metrics['added_km1']/weight
    fractions=local_fractions(data,baseline['membership'],labels)
    metrics['maximum_local_split_fraction']=max(v['fraction'] for v in fractions.values())
    s['local_connection_constraints']=fractions
    (run/'candidates'/name/'summary.json').write_text(json.dumps(s,indent=2)+'\n')
    return name


def import_previous(run,previous):
    data,baseline,cfg,cores=context(run);names=[]
    for seed in (0,1):
        source=previous/f'candidates/stage3_k4_s{seed}'
        groups=json.loads((source/'groups.json').read_text())
        summary=json.loads((source/'summary.json').read_text())
        parent=summary['provenance']['logical_parent']
        name=persist(run,f'previous_four_s{seed}',data,baseline,cfg,cores,groups,
            dict(kind='imported_resource_four_children',parent=parent,source=str(source),seed=seed))
        names.append(name)
    return names


def combine(run):
    data,baseline,cfg,cores=context(run)
    base=json.loads((run/'candidates/baseline5/balanced_regions.json').read_text())
    options={}
    for f in sorted((run/'candidates').glob('*/balanced_regions.json')):
        s=json.loads((f.parent/'summary.json').read_text());r=json.loads(f.read_text())
        parent=s['provenance'].get('parent')
        if parent is None or r['status']!='feasible' or not admissible(s['metrics'],cfg):continue
        if r['objective']>=base['objective']:continue
        groups=json.loads((f.parent/'groups.json').read_text());p=int(parent[1:])
        children=[g for g in groups if all(baseline['membership'][a]==p for a in g)]
        if sum(map(len,children))!=len(baseline['groups'][p]):continue
        candidate=(r['objective'],f.parent.name,children)
        if p not in options or candidate[0]<options[p][0]:options[p]=candidate
    order=sorted(options,key=lambda p:options[p][0]);selected={};names=[]
    for p in order:
        selected[p]=options[p]
        if len(selected)<2:continue
        groups=[child for i,g in enumerate(baseline['groups']) for child in
                (selected[i][2] if i in selected else [g])]
        suffix=hashlib.sha256(json.dumps({str(i):x[1] for i,x in selected.items()},sort_keys=True).encode()).hexdigest()[:6]
        name=persist(run,f'combine_{len(selected)}_{suffix}',data,baseline,cfg,cores,groups,
            dict(kind='combined_best_local_candidates',components={f'P{i:02d}':x[1] for i,x in selected.items()}))
        names.append(name)
    (run/'combination_proposals.json').write_text(json.dumps(dict(order=order,candidates=names),indent=2)+'\n')
    return names


def merge(run,input_name):
    data,baseline,cfg,cores=context(run)
    f=run/'candidates'/input_name;s=json.loads((f/'summary.json').read_text())
    groups=json.loads((f/'groups.json').read_text());pairs=Counter()
    for e in s['connections']:
        pairs[tuple(sorted((int(e['source'][1:]),int(e['sink'][1:]))))]+=e['weighted_nets']
    selected=set(p for p,_ in pairs.most_common(4))
    parent=[max(m['baseline_parent_cells'],key=m['baseline_parent_cells'].get) for m in s['modules']]
    for a,b in pairs:
        if parent[a]==parent[b]:selected.add((a,b))
    names=[]
    for a,b in sorted(selected):
        proposal=[g for i,g in enumerate(groups) if i not in (a,b)]+[groups[a]+groups[b]]
        names.append(persist(run,f'{input_name}_merge_{a}_{b}',data,baseline,cfg,cores,proposal,
                     dict(kind='reverse_merge',input_candidate=input_name,pair=[a,b])))
    return names


def refine(run,input_name):
    data,baseline,cfg,cores=context(run)
    groups=json.loads((run/'candidates'/input_name/'groups.json').read_text())
    cap=sum(len(g) for g in data['atoms'])
    revised,batch=relocate_cores(data,groups,cores,strength=cfg['core_soft_strength'],
                                cell_cap=cap,max_moves=32)
    revised,atomic=boundary_refine(data,revised,cores,strength=cfg['core_soft_strength'],
                                   rounds=2,cell_cap=cap)
    name=persist(run,input_name+'_refined',data,baseline,cfg,cores,revised,
        dict(kind='core_and_atom_refinement',input_candidate=input_name,batch_moves=batch,atom_moves=atomic))
    return [name]


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['import','combine','merge','refine'])
    p.add_argument('run',type=Path);p.add_argument('--previous',type=Path);p.add_argument('--candidate')
    a=p.parse_args()
    if a.action=='import':names=import_previous(a.run,a.previous)
    elif a.action=='combine':names=combine(a.run)
    elif a.action=='merge':names=merge(a.run,a.candidate)
    else:names=refine(a.run,a.candidate)
    (a.run/f'{a.action}_names.json').write_text(json.dumps(names)+'\n')
    print(json.dumps(dict(action=a.action,candidates=names)),flush=True)
