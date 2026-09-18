"""Exploratory whole-core moves after atom-only refinement reaches a fixed point."""
import argparse
import json
from collections import Counter
from pathlib import Path

import partition as base
from improve import (boundary_refine, core_metrics, labels_for, load_context,
                     logical_cores, objective, save_candidate, soft_edges)


def batch_gain(counts,moving_counts,target,weight):
    after=set(counts)
    for source,n in moving_counts.items():
        if counts[source]==n: after.remove(source)
    after.add(target)
    return weight*(len(counts)-len(after))


def relocate_cores(data,groups,cores,strength=.02,budget=.02,cell_cap=150000,max_moves=32):
    labels=labels_for(data,groups)
    real_count=len(data['edges']);edges=data['edges']+soft_edges(cores,strength)
    incident=[[] for _ in data['atoms']];counts=[]
    for e,(pins,w) in enumerate(edges):
        counts.append(Counter(labels[a] for a in pins))
        for a in pins: incident[a].append(e)
    sizes=[sum(len(data['atoms'][a]) for a in g) for g in groups]
    demand=[base.demand_of(data,g) for g in groups]
    original_real=objective(data['edges'],labels)[0]*4;current_real=original_real
    history=[]
    for iteration in range(max_moves):
        best=None
        for ci,core in enumerate(cores):
            destinations=sorted({labels[a] for a in core['atoms']})
            if len(destinations)<2: continue
            for target in destinations:
                moving=[a for a in core['atoms'] if labels[a]!=target]
                moved_cells=sum(len(data['atoms'][a]) for a in moving)
                if sizes[target]+moved_cells>cell_cap: continue
                addition=base.demand_of(data,moving)
                if any(demand[target][r]+addition[r]>cap for r,cap in base.CAPS.items()): continue
                removal=Counter()
                for a in moving: removal[labels[a]]+=len(data['atoms'][a])
                if any(removal[m]==sizes[m] for m in removal): continue
                changed={}
                for a in moving:
                    for e in incident[a]:
                        changed.setdefault(e,Counter())[labels[a]]+=1
                gain=real_gain=0
                for e,removals in changed.items():
                    delta=batch_gain(counts[e],removals,target,edges[e][1]);gain+=delta
                    if e<real_count: real_gain+=delta
                if gain<=0 or current_real-real_gain>original_real*(1+budget): continue
                score=(gain,real_gain,-ci,-target)
                if best is None or score>best[0]:
                    best=(score,moving,changed,addition,removal)
        if best is None: break
        score,moving,changed,addition,removal=best
        gain,real_gain,negative_ci,negative_target=score;target=-negative_target
        for e,removals in changed.items():
            for source,n in removals.items():
                counts[e][source]-=n
                if not counts[e][source]: del counts[e][source]
            counts[e][target]+=sum(removals.values())
        for a in moving:
            source=labels[a];labels[a]=target
            demand[source].subtract(data['atom_resources'][a])
        for source,n in removal.items(): sizes[source]-=n
        sizes[target]+=sum(removal.values());demand[target].update(addition)
        current_real-=real_gain
        history.append(dict(core=cores[-negative_ci]['hierarchy'],target=target,
            moved_cells=sum(removal.values()),real_gain=real_gain/4,augmented_gain=gain/4))
    assert objective(data['edges'],labels)[0]*4==current_real
    output=[[] for _ in groups]
    for a in data['active_atoms']: output[labels[a]].append(a)
    return output,history


def run_exploration(run,input_name):
    data,original,baseline,reference=load_context(run)
    common=json.loads((run/'cores.json').read_text())
    cores=logical_cores(data,cohesion=.2)
    groups=json.loads((run/'candidates'/input_name/'groups.json').read_text())
    base.log('expanded_cores',count=len(cores),cells=sum(c['cells'] for c in cores),
             input=input_name,**{k:v for k,v in core_metrics(data,labels_for(data,groups),cores).items() if k!='cores'})
    for strength in (0,.02,.10):
        refined,history=relocate_cores(data,groups,cores,strength=strength)
        refined,atom_history=boundary_refine(data,refined,cores,strength=strength)
        # The total budget also applies across both refinement mechanisms.
        if objective(data['edges'],labels_for(data,refined))[0] > objective(data['edges'],labels_for(data,groups))[0]*1.02:
            base.log('exploration_budget_rejected',strength=strength,input=input_name)
            continue
        name=f'{input_name}_corebatch_{strength:g}'
        save_candidate(run,name,data,refined,common,baseline['membership'],
            dict(exploratory=True,input_candidate=input_name,core_cohesion=.2,strength=strength,
                 batch_moves=history,atom_moves=atom_history,
                 expanded_core_before=core_metrics(data,labels_for(data,groups),cores),
                 expanded_core_after=core_metrics(data,labels_for(data,refined),cores)))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('run',type=Path);p.add_argument('input_name')
    a=p.parse_args();run_exploration(a.run,a.input_name)
