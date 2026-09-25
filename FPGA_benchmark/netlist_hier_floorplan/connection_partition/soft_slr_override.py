"""User-requested S01 whole-SLR2 soft region, applied after RAM padding."""
import copy
import hashlib
import json
import pickle
import shutil
import sys
from pathlib import Path
from static_regions import RESOURCES,load_device,all_rectangles,overlap_audit
from directed_model import DirectedModel

def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(8*1024*1024),b''):h.update(b)
    return h.hexdigest()

def write(p,v):p.write_text(json.dumps(v,indent=2)+'\n')

def generate(run,previous):
    prior=json.loads((previous/'solution.json').read_text());meta=json.loads((previous/'export/modules.json').read_text())
    paths=[p for p in (previous/'export').iterdir() if p.is_file()]
    paths += [previous/'input/cr.tsv',previous/'netmodel.pkl',previous/'directed.json',previous/'core_solution.json']
    paths += [p for p in (previous/'implementation_input').rglob('*') if p.is_file()]
    immutable={str(p):sha(p) for p in paths}
    (run/'input').mkdir(exist_ok=True);shutil.copytree(previous/'export',run/'input/export')
    shutil.copy2(previous/'input/cr.tsv',run/'input/cr.tsv')
    for name in ['netmodel.pkl','directed.json','core_solution.json']:shutil.copy2(previous/name,run/name)
    device=load_device(run/'input/cr.tsv');slr2={c for c,d in device.items() if d['slr']==2}
    region=next(r for r in all_rectangles(device) if set(r['crs'])==slr2)
    assert region['bounds']==[0,8,7,11] and region['area']==32
    chosen=copy.deepcopy(prior['regions']);chosen['S01']=region
    for m in chosen:
        if m!='S01':assert chosen[m]==prior['regions'][m]
    override=dict(schema='user-soft-slr-override-v1',module='S01',slr=2,IS_SOFT=True,
        previous_bounds=prior['regions']['S01']['bounds'],final_bounds=region['bounds'],clock_regions=region['crs'],
        application_order='after inherited RAM-right padding',
        semantics='Allowed initial soft placement region, not uniform physical occupancy or hard SLR confinement.',
        authorization='User explicitly requested S01 soft Pblock to cover all SLR2 for an implementation comparison.',
        planning_constraints='Original area-window and uniform-overlap constraints are not acceptance gates for this soft override. Individual capacities and geometry are checked.')
    with (run/'netmodel.pkl').open('rb') as f:netmodel=pickle.load(f)
    cfg=prior['configuration'];dm=DirectedModel(json.loads((run/'directed.json').read_text()),device,cfg)
    base=netmodel.components({f'P{i:02d}':chosen[f'S{i:02d}'] for i in range(11)},cfg['slr_distance_weight'])
    extra=dm.components(chosen,True);fixed=prior['components']['fixed_partition_cost']
    comp=dict(base,**extra,fixed_partition_cost=fixed,old_J=base['physical_cost']+fixed)
    comp['J']=comp['old_J']+extra['directed_term']+extra['branch_square_term']
    audit=overlap_audit(meta['modules'],chosen,device,prior['limits'])
    budgets={}
    for slr in range(4):
        capacity={r:sum(d['resources'][r] for d in device.values() if d['slr']==slr) for r in RESOURCES}
        demand={r:sum(m[r] for m in meta['modules'] if chosen[m['module_id']]['slrs']==[slr]) for r in RESOURCES}
        budgets[str(slr)]=dict(capacity=capacity,demand=demand,
            utilization={r:demand[r]/capacity[r] if capacity[r] else 0 for r in RESOURCES},
            within_inherited_total_budget=all(demand[r]<=capacity[r]*prior['limits'][r]+1e-8 for r in RESOURCES))
    assert all(v['within_inherited_total_budget'] for v in budgets.values())
    result=copy.deepcopy(prior)
    result.update(status='soft_override_ready',tag='S01_whole_SLR2_soft',regions=chosen,components=comp,
        objective=comp['J'],objective_role='uniform_distribution_diagnostic_only_not_optimized_or_predicted_placement',
        overlap=audit,uniform_overlap_pass=audit['valid'],soft_override=override,
        acceptance='Export geometry/members and whole-SLR resource totals verified; actual placement/route not run.',
        slr_resource_budgets=budgets,total_module_crs=sum(r['area'] for r in chosen.values()),
        families=dm.family_audit(chosen),maximum_slrs_per_unit=1,
        search_certificate='User-selected soft-region override; no new optimization or global optimality claim.',
        timing_validation='Not run for S01 whole-SLR2.',
        physical_model='Uniform capacity-weighted diagnostics retained for transparency; desired placement can use nonuniform residual resources.')
    write(run/'solution.json',result);write(run/'override.json',override)
    write(run/'comparison.json',dict(previous=prior['components'],override_uniform_diagnostic=comp,
        previous_region=prior['regions']['S01'],new_region=region,slr_resource_budgets=budgets))
    shutil.copytree(run/'input/export',run/'export');write(run/'export/static_regions.json',result)
    # Reuse the verified membership verbatim; only the final region data changes.
    shutil.copytree(previous/'implementation_input',run/'implementation_input')
    write(run/'implementation_input/export/static_regions.json',result)
    write(run/'implementation_input/override.json',override)
    lines=['# S01 whole-SLR2 user override, applied after RAM padding.','set planned_regions [dict create]','set planned_bounds [dict create]']
    for mid,r in sorted(chosen.items()):
        lines.append(f'dict set planned_regions {mid} {{{" ".join(r["crs"])}}}')
        lines.append(f'dict set planned_bounds {mid} {{{" ".join(map(str,r["bounds"]))}}}')
    (run/'implementation_input/regions.tcl').write_text('\n'.join(lines)+'\n')
    manifest=json.loads((run/'implementation_input/manifest.json').read_text())
    manifest.update(source=str(run/'export'),soft_override='override.json',
        scope='Frozen memberships; S01 whole-SLR2 soft envelope, other ten RAM-padded regions unchanged. Uniform per-CR occupancy is diagnostic only.')
    manifest['files']={str(p.relative_to(run/'implementation_input')):sha(p) for p in (run/'implementation_input').rglob('*') if p.is_file() and p.name!='manifest.json'}
    write(run/'implementation_input/manifest.json',manifest)
    write(run/'binding.json',dict(previous=str(previous),input_dcp=meta['input_dcp'],input_sha256=meta['input_sha256'],
        immutable_files=immutable,fixed_partition_cost=fixed,total_leaf_cells=meta['validation']['all_cells'],
        scope='Only S01 exported soft Pblock changes to whole SLR2. No P&R, STA, fanout, partition or Git.'))
    for p,h in immutable.items():assert sha(p)==h,p
    print(json.dumps(dict(stage='exported',S01=region['bounds'],uniform_overlap_pass=audit['valid'],
        diagnostic_J=comp['J'],SLR2_LUT=budgets['2']['utilization']['LUT'])),flush=True)

if __name__=='__main__':generate(Path(sys.argv[1]),Path(sys.argv[2]))
