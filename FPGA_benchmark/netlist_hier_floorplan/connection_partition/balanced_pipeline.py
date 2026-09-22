"""Finish the bounded experiment after candidate generation, preserving baselines."""
import argparse
import copy
import json
import pickle
import time
from pathlib import Path

from balanced_search import combine, merge, refine
from balanced_regions import evaluate, options_for, polish
from balanced_deliver import select, deliver
from balanced_physical import NetModel
from improve import labels_for
from static_regions import load_device, all_rectangles
from plot_static_comparison import main as plot


def stability(run,name):
    with (run/'graph.pkl').open('rb') as f:data=pickle.load(f)
    cfg=json.loads((run/'source/balanced_config.json').read_text())
    folder=run/'candidates'/name
    summary=json.loads((folder/'summary.json').read_text())
    original=json.loads((folder/'balanced_regions.json').read_text())
    groups=json.loads((folder/'groups.json').read_text())
    device=load_device(run/'cr.tsv');rectangles=all_rectangles(device)
    netmodel=NetModel(data,labels_for(data,groups),len(groups),device)
    options={m['module_id']:options_for(m,rectangles,cfg)[0] for m in summary['modules']}
    unary={m['module_id']:[netmodel.internal_region_cost(i,r) for r in options[m['module_id']]]
            for i,m in enumerate(summary['modules'])}
    runs=[]
    for seed in (1,2):
        chosen,comp,history=polish(copy.deepcopy(original['regions']),summary['modules'],options,
                                  netmodel,device,cfg,unary,seed)
        runs.append(dict(seed=seed,components=comp,history=history,
            relative_improvement=(original['components']['physical_cost']-comp['physical_cost'])/original['components']['physical_cost']))
    (run/'region_stability.json').write_text(json.dumps(dict(candidate=name,
        scope='Further coordinate search from the selected plan, two different proposal orders; diagnostic only, primary plan unchanged.',
        runs=runs),indent=2)+'\n')


def main(run):
    start=time.monotonic()
    while not (run/'generation_complete.json').exists() or not (run/'combine_first.exit').exists():
        if time.monotonic()-start>7200:raise TimeoutError('Generation did not finish in the diagnostic waiting window')
        time.sleep(10)
    assert (run/'combine_first.exit').read_text().strip()=='0'
    names=[p.parent.name for p in sorted((run/'candidates').glob('*/summary.json'))]
    evaluate(run,names)
    evaluate(run,combine(run))
    first=select(run)
    (run/'selection_before_merges.json').write_text((run/'selection.json').read_text())
    evaluate(run,merge(run,first))
    second=select(run)
    (run/'selection_before_refinement.json').write_text((run/'selection.json').read_text())
    evaluate(run,refine(run,second))
    final=select(run)
    stability(run,final)
    deliver(run,final)
    plot(run,final,baseline_name='baseline5',result_file='balanced_regions.json',id_prefix='B')
    (run/'pipeline_complete.json').write_text(json.dumps(dict(selected=final,elapsed_seconds=time.monotonic()-start),indent=2)+'\n')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('run',type=Path);a=p.parse_args();main(a.run)
