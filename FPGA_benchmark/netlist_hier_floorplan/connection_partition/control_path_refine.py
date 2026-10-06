"""Optional control-cone membership repair and cumulative-path floorplanning."""
import argparse
from collections import Counter
import csv
import gzip
import json
from pathlib import Path
import pickle
import time

from chain_regions import BranchCost, directed_edges
from control_cones import discover
from control_path_cost import PathModel, bind_paths, parse_timing
from improve import digest, objective, soft_edges, logical_cores
from joint_units import load_protection, require_intact
from resource_partition import Budget, profile_from_cr_table
from static_regions import RESOURCES, load_device, overlap_audit, all_rectangles, fits


def load(path): return json.loads(Path(path).read_text())
def dump(path,value): Path(path).write_text(json.dumps(value,indent=2,ensure_ascii=False)+'\n')


def complete_run(out,progress,seconds,changed_cells,cost):
    """Finish the progress log before hashing it into the output certificate."""
    if (out/'complete.json').exists():raise FileExistsError(out/'complete.json')
    progress(dict(stage='complete',seconds=seconds,changed_cells=changed_cells,J=cost))
    dump(out/'complete.json',dict(status='PASS',seconds=seconds,
        files={str(p.relative_to(out)):digest(p) for p in out.rglob('*') if p.is_file()}))


class Refinement:
    def __init__(self,data,owners,meta,regions,parent_of,device,directed_cfg,cfg,feedback,units,cores,budget):
        self.data=data; self.owners=list(owners); self.original_owners=list(owners)
        self.regions=dict(regions); self.parent_of=parent_of; self.device=device; self.cfg=cfg
        self.limits=directed_cfg['resource_limits']; self.units=units; self.budget=budget
        self.ids=[m['module_id'] for m in meta['modules']]
        self.labels=[owners[g[0]] for g in data['atoms']]
        assert all({owners[c] for c in g}=={self.labels[a]} for a,g in enumerate(data['atoms']))
        self.demands={m['module_id']:Counter({r:m[r] for r in RESOURCES}) for m in meta['modules']}
        self.cells={m['module_id']:m['cells'] for m in meta['modules']}
        self.movable={a for u in units for a in u['atoms']}
        self.node_of=[f'A{a}' if a in self.movable else self.labels[a] for a in range(len(data['atoms']))]
        self.nodes={m:dict(resources=Counter(),cells=0) for m in self.ids}
        self.node_group={m:m for m in self.ids}
        for a,n in enumerate(self.node_of):
            if n not in self.nodes:self.nodes[n]=dict(resources=Counter(),cells=0)
            self.nodes[n]['resources'].update(data['atom_resources'][a])
            self.nodes[n]['cells']+=len(data['atoms'][a]);self.node_group[n]=self.labels[a]
        self.edges,self.directed_coverage=directed_edges(data,self.node_of)
        self.branch=BranchCost(device,directed_cfg);self.path=PathModel(data,feedback,cfg)
        self.logical_edges=soft_edges(cores,cfg['core_soft_strength'])
        self.affected_edges=[(e,w) for e,w in data['edges'] if any(a in self.movable for a in e)]
        initial=[parent_of[m] for m in self.labels]
        self.initial_cut=objective(data['edges'],initial)[0]
        self.fixed_cut=self.initial_cut-objective(self.affected_edges,initial)[0]
        self.history=[]; self.trials=[]

    def logical_metrics(self):
        labels=[self.parent_of[m] for m in self.labels]
        c=self.fixed_cut+objective(self.affected_edges,labels)[0]
        l=objective(self.logical_edges,labels)[0]
        return dict(C=c,L=l,J_partition=self.cfg['cut_weight']*c+self.cfg['logical_core_weight']*l)

    def modules(self):
        return [dict(module_id=m,cells=self.cells[m],**{r:self.demands[m][r] for r in RESOURCES}) for m in self.ids]

    def legal(self):
        if any(self.cells[m]<=0 or not fits(self.demands[m],self.regions[m],self.limits) for m in self.ids):return False
        logical={p:Counter() for p in set(self.parent_of.values())}
        for m,q in self.demands.items():logical[self.parent_of[m]].update(q)
        if not all(self.budget.fits(q) for q in logical.values()):return False
        if not overlap_audit(self.modules(),self.regions,self.device,self.limits)['valid']:return False
        return self.logical_metrics()['C'] <= self.initial_cut*(1+self.cfg['max_partition_cut_increase_fraction'])+1e-9

    def score(self,details=False):
        logical=self.logical_metrics()
        regions={n:self.regions[m] for n,m in self.node_group.items()}
        directed=self.branch.total(self.edges,regions)
        path=self.path.evaluate(self.owners,self.regions,details)
        return dict(**logical, directed_cost=directed, **path,
                    J_control=logical['J_partition']+directed+path['path_square_term'])

    def move(self,unit,target):
        old={a:self.labels[a] for a in unit['atoms']}
        self.restore({a:target for a in unit['atoms']})
        return old

    def restore(self,assignments):
        for a,target in assignments.items():
            source=self.labels[a]
            if source==target:continue
            q=self.data['atom_resources'][a];n=len(self.data['atoms'][a])
            self.demands[source].subtract(q);self.demands[target].update(q)
            self.cells[source]-=n;self.cells[target]+=n
            self.labels[a]=target;self.node_group[self.node_of[a]]=target
            for c in self.data['atoms'][a]:self.owners[c]=target

    def repair(self,progress):
        current=self.score()
        for iteration in range(self.cfg['max_rounds']):
            changed=0
            for unit in sorted(self.units,key=lambda u:(min(u['ranks']),u['id'])):
                best=None; best_score=current
                for target in unit['options']:
                    if all(self.labels[a]==target for a in unit['atoms']):continue
                    old=self.move(unit,target)
                    feasible=self.legal()
                    trial=dict(unit=unit['id'],round=iteration,target=target,feasible=feasible)
                    if feasible:
                        candidate=self.score()
                        trial.update(delta={k:candidate[k]-current[k] for k in
                            ('C','L','directed_cost','path_square_term','J_control')})
                        if candidate['J_control'] < best_score['J_control']-1e-6:
                            best=target;best_score=candidate
                    self.trials.append(trial)
                    self.restore(old)
                if best is not None:
                    old=self.move(unit,best);changed+=1;current=best_score
                    row=dict(stage='control_move',round=iteration,unit=unit['id'],kind=unit['kind'],
                        target=best,moved_atoms=sum(v!=best for v in old.values()),
                        cells=sum(len(self.data['atoms'][a]) for a,v in old.items() if v!=best),
                        J=current['J_control'],endpoints_over_one=current['endpoints_over_one'])
                    self.history.append(row);progress(row)
            if not changed:break
        return current

    def floorplan(self,progress):
        """Reposition only small non-memory/non-DSP modules, retaining their shape."""
        current=self.score();rectangles=all_rectangles(self.device)
        movable=[m for m in self.ids if self.regions[m]['area']<=4 and
                 not any(self.demands[m][r] for r in ('DSP','BRAM18','URAM'))]
        for mid in movable:
            old=self.regions[mid];x0,y0,x1,y1=old['bounds'];best=old;value=current
            for region in rectangles:
                a,b,c,d=region['bounds']
                if len(region['slrs'])!=1 or (c-a,d-b)!=(x1-x0,y1-y0):continue
                self.regions[mid]=region
                if self.legal():
                    trial=self.score()
                    if trial['J_control']<value['J_control']-1e-6:best=region;value=trial
            self.regions[mid]=best;current=value
            if best['bounds']!=old['bounds']:
                row=dict(stage='control_region',module=mid,before=old['bounds'],after=best['bounds'],
                         J=current['J_control'],endpoints_over_one=current['endpoints_over_one'])
                self.history.append(row);progress(row)
        return current


def run(partition_run,baseline_input,timing_report,output,config=None):
    start=time.monotonic();root=Path(partition_run).resolve();impl=Path(baseline_input).resolve()
    timing=Path(timing_report).resolve();out=Path(output).resolve()
    if out.exists():raise FileExistsError(out)
    cfg=load(config or Path(__file__).with_name('control_path_config.json'))
    meta=load(impl/'export/modules.json');manifest=load(impl/'manifest.json')
    for name,h in manifest['files'].items():
        p=(impl/name).resolve()
        if impl not in p.parents or digest(p)!=h:raise ValueError('Input manifest mismatch: '+name)
    sources={str(p):digest(p) for p in [root/'graph.pkl',root/'cr.tsv',impl/'manifest.json',timing,
        root/'source/balanced_config.json',root/'source/resource_partition_config.json',
        root/'floorplan/source/directed_config.json',root/'protection_manifest.json']}
    assert digest(Path(meta['input_dcp']))==meta['input_sha256']
    with (root/'graph.pkl').open('rb') as f:data=pickle.load(f)
    with gzip.open(impl/'export/leaf_cells.tsv.gz','rt') as f:
        rows=list(csv.DictReader(f,delimiter='\t'))
    assert len(rows)==len(data['cells'])
    for c,r in zip(data['cells'],rows):
        assert all(c[k]==r[k] for k in ('cell_id','cell_name','primitive','original_hierarchy'))
    owners=[r['module_id'] for r in rows];del rows
    protected,joint,protection_manifest=load_protection(root)
    require_intact([owners[g[0]] for g in data['atoms']],protected,'control refinement input')
    parent_of=load(impl/'physical_to_logical.json')
    core=load(impl/'core_solution.json');regions=core['regions']
    device=load_device(root/'cr.tsv');dcfg=load(root/'floorplan/source/directed_config.json')
    pcfg=load(root/'source/resource_partition_config.json')
    bcfg=load(root/'source/balanced_config.json')
    cfg.update({k:bcfg[k] for k in ('core_soft_strength','cut_weight','logical_core_weight')})
    if cfg['path_square_weight']<0 or cfg['criticality_window_ns']<=0:
        raise ValueError('Invalid path cost configuration')
    if not 1<=cfg['criticality_floor']<=cfg['criticality_ceiling']:
        raise ValueError('Criticality weights must be ordered and at least one')
    budget=Budget(profile_from_cr_table(root/'cr.tsv',pcfg['resource_ratios']))
    feedback=bind_paths(data,parse_timing(timing.read_text()),cfg)
    if not feedback['paths']:
        raise ValueError('No reported timing path can be bound to the original netlist')
    units=discover(data,feedback,joint,protected,owners,cfg)
    core_cache=root/'balanced/cores.json'
    cores=load(core_cache) if core_cache.exists() else logical_cores(data,
        bcfg['core_min_cells'],bcfg['core_max_cells'],bcfg['core_min_cohesion'])
    model=Refinement(data,owners,meta,regions,parent_of,device,dcfg,cfg,feedback,units['units'],cores,budget)
    out.mkdir(parents=True)
    dump(out/'logical_cores.json',cores)
    dump(out/'config.json',cfg);dump(out/'feedback.json',feedback);dump(out/'control_units.json',units)
    dump(out/'coverage.json',model.path.coverage)
    dump(out/'source_binding.json',dict(inputs=sources,source_files={p.name:digest(p) for p in Path(__file__).parent.iterdir() if p.is_file()}))
    def progress(row):
        print(json.dumps(row),flush=True)
        with (out/'progress.jsonl').open('a') as f:f.write(json.dumps(row)+'\n')
    assert model.legal()
    before=model.score(True);dump(out/'before.json',before)
    progress(dict(stage='baseline',control_units=len(units['units']),coverage=feedback['coverage'],J=before['J_control']))
    model.repair(progress)
    model.floorplan(progress)
    model.repair(progress)
    after=model.score(True);dump(out/'after.json',after)
    require_intact(model.labels,protected,'control refinement output')
    assert model.legal() and after['J_control']<=before['J_control']+1e-6
    changes=[dict(cell_id=f'c{i}',cell=c['cell_name'],before=owners[i],after=model.owners[i],
                  logical_before=parent_of.get(owners[i],owners[i]),logical_after=parent_of.get(model.owners[i],model.owners[i]))
             for i,c in enumerate(data['cells']) if owners[i]!=model.owners[i]]
    dump(out/'membership_changes.json',changes)
    dump(out/'history.json',model.history)
    dump(out/'candidate_trials.json',model.trials)
    worst=feedback['paths'][min(range(len(feedback['paths'])),key=lambda i:feedback['paths'][i]['rank'])]
    dump(out/'worst_path_cells.json',[
        dict(cell=data['cells'][c]['cell_name'],primitive=data['cells'][c]['primitive'],
             before=owners[c],after=model.owners[c],before_slr=regions[owners[c]]['slrs'],
             after_slr=model.regions[model.owners[c]]['slrs']) for c in worst['cell_ids']])
    from control_path_export import export_and_verify
    summary=export_and_verify(out,root,impl,data,model,meta,core,protected,joint,protection_manifest,before,after,cfg)
    assert all(digest(Path(p))==h for p,h in sources.items())
    summary['seconds']=time.monotonic()-start;dump(out/'summary.json',summary)
    complete_run(out,progress,summary['seconds'],len(changes),after['J_control'])
    return summary


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('partition_run');p.add_argument('baseline_input');p.add_argument('timing_report');p.add_argument('output')
    p.add_argument('--config')
    a=p.parse_args();run(a.partition_run,a.baseline_input,a.timing_report,a.output,a.config)
