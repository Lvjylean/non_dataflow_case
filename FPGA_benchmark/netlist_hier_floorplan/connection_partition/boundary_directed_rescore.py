"""Graph-bound fixed-layout comparison, without search, export, or P&R."""
import argparse
import json
from pathlib import Path
import pickle
import time

from boundary_hyper import BoundaryNetModel, independent_spans
from boundary_directed import SCHEMA, attach, independent_components
from directed_model import DirectedModel
from directed_spatial_cache import original
from improve import digest
from static_regions import load_device


def compare(run,graph,output):
    if output.exists():
        raise FileExistsError(output)
    started=time.monotonic()
    load=lambda p:json.loads(p.read_text())
    solution=load(run/'solution.json');old_cfg=solution['configuration']
    data,labels,ids=original(run,graph)
    device=load_device(run/'input/cr.tsv');raw=load(run/'directed.json')
    raw=dict(raw,module_ids=ids)
    old=DirectedModel(raw,device,old_cfg).components(solution['regions'],True)
    for k,v in old.items():
        if isinstance(v,(int,float)):
            assert abs(v-solution['components'][k])<max(1e-6,abs(v)*1e-10),(k,v,solution['components'][k])
    model=BoundaryNetModel(data,labels,len(ids),device,old_cfg.get('boundary_frontier_max_entries',10000000))
    cfg=dict(old_cfg,directed_distance_model=SCHEMA)
    lifted=attach(raw,model,cfg)
    lifted['spatial']['binding']=dict(module_ids=ids,graph_sha256=digest(graph),
        membership_sha256=digest(run/'input/export/leaf_cells.tsv.gz'))
    scorer=DirectedModel(lifted,device,cfg)
    new=scorer.components(solution['regions'],True)
    independent=independent_components(lifted['spatial'],solution['regions'],device,cfg,ids)
    for k,v in independent.items():
        assert abs(v-new[k])<max(1e-6,abs(v)*1e-10),(k,v,new[k])
    for k in ('branch_square','branch_square_term','raw_far_pins','raw_branch_boundaries','raw_boundary_histogram'):
        assert old[k]==new[k],k
    chosen={f'P{i:02d}':solution['regions'][m] for i,m in enumerate(ids)}
    physical=independent_spans(model,chosen)
    physical_value=physical['x']+physical['y']+cfg['slr_distance_weight']*physical['slr']
    assert abs(physical_value-solution['components']['physical_cost'])<max(1e-6,abs(physical_value)*1e-10)
    from path_cache import read
    from cumulative_paths import independent_score,settings
    path=independent_score(read(run),solution['regions'],settings(cfg))
    assert path['cumulative_path_term']==solution['components']['cumulative_path_term']
    before=solution['components'];after=dict(before,**new)
    after['J']=before['J']-old['directed_term']+new['directed_term']
    result=dict(status='PASS',scope='Same original post-opt graph, membership and regions; only directed spatial distance changed. No search or new implementation input.',
        source=str(run),configuration=cfg,before=before,after=after,independent_directed=independent,
        independent_hyper=physical,independent_paths=path,
        audit=lifted['spatial']['audit'],seconds=time.monotonic()-started,
        inputs={str(p):digest(p) for p in [graph,run/'solution.json',run/'directed.json',run/'input/cr.tsv',run/'input/export/leaf_cells.tsv.gz']})
    output.mkdir(parents=True)
    (output/'comparison.json').write_text(json.dumps(result,indent=2)+'\n')
    (output/'directed_spatial.json').write_text(json.dumps(lifted['spatial'],indent=2)+'\n')
    (output/'manifest.json').write_text(json.dumps({p.name:digest(p) for p in output.iterdir() if p.is_file()},indent=2)+'\n')
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('run','graph','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    r=compare(args.run,args.graph,args.output)
    print(json.dumps({k:r[k] for k in ('status','before','after','seconds')}),flush=True)
