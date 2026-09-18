"""Use a four-child search as proposals, then merge only physically feasible pairs."""
import argparse
import json
from pathlib import Path

import partition as base
from improve import load_context, save_candidate
from static_regions import all_rectangles, candidates, load_device


def pairings(items):
    if not items:
        yield [];return
    first=items[0]
    for i in range(1,len(items)):
        rest=items[1:i]+items[i+1:]
        for tail in pairings(rest):
            yield [(first,items[i])]+tail


def main(run,input_name):
    data,original,baseline,reference=load_context(run)
    cores=json.loads((run/'cores.json').read_text())
    folder=run/'candidates'/input_name
    summary=json.loads((folder/'summary.json').read_text())
    groups=json.loads((folder/'groups.json').read_text())
    heavy=[i for i,m in enumerate(summary['modules']) if m['URAM']]
    if len(heavy)!=4: raise ValueError('This bounded comparison requires exactly four resource-heavy children')
    device=load_device(run/'cr.tsv');regions=all_rectangles(device)
    for number,matching in enumerate(pairings(heavy)):
        merged=[groups[a]+groups[b] for a,b in matching]
        geometry=[]
        for group in merged:
            demand=base.demand_of(data,group)
            _,stats=candidates(demand,regions)
            geometry.append(stats)
            if not base.fits(data,group,150000) or stats.get('min_slrs')!=1:
                break
        else:
            final=[g for i,g in enumerate(groups) if i not in heavy]+merged
            save_candidate(run,f'{input_name}_regroup_{number}',data,final,cores,baseline['membership'],
                dict(input_candidate=input_name,matching=matching,local_geometry=geometry,
                     policy='Merge proposed children only if actual static CR resources admit one-SLR regions; joint overlap checked separately.'))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('run',type=Path);p.add_argument('input_name')
    a=p.parse_args();main(a.run,a.input_name)
