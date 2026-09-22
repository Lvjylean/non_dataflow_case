"""Export the requested edge-padding rule using frozen netlist and connection caches."""
import copy
import hashlib
import json
import shutil
import sys
from pathlib import Path
from static_regions import RESOURCES, load_device
from edge_padding import expand, regions_tcl, geometry_adapter


def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(8*1024*1024),b''):h.update(b)
    return h.hexdigest()


def write(p,v):p.write_text(json.dumps(v,indent=2)+'\n')


def validate_core(plan):
    if plan.get('status')!='feasible' or not plan.get('overlap',{}).get('valid'):
        raise ValueError('Use the resource-feasible J-selected core floorplan.')
    if any(k in plan for k in ['soft_padding','soft_override','edge_padding']):
        raise ValueError('Use the unexpanded core; previous RAM padding/SLR overrides are not inputs to this flow.')


def build_envelope(modules,prior,device,reference):
    """Separate planning estimates from exported geometry without cost-cache I/O."""
    validate_core(prior)
    chosen,changes=expand(modules,prior,device)
    # The soft envelope is geometry only. Never redistribute demand, recompute
    # communication cost, or credit its added resources to the selected core.
    planning=copy.deepcopy(prior['regions'])
    for mid,region in chosen.items():
        region.pop('capacity',None)
        region['geometry_role']='soft_allowance_only'
        region['core_crs']=list(planning[mid]['crs'])
        region['padding_crs']=sorted(set(region['crs'])-set(planning[mid]['crs']))
    comp=copy.deepcopy(prior['components']);fixed=comp['fixed_partition_cost']
    audit=copy.deepcopy(prior['overlap'])
    covers={c:sum(c in r['crs'] for r in chosen.values()) for c in device}
    soft_geometry=dict(total_module_crs=sum(r['area'] for r in chosen.values()),
        occupied_crs=sum(v>0 for v in covers.values()),overlapping_crs=sum(v>1 for v in covers.values()))
    budgets={}
    assert all(len(r['slrs'])==1 for r in chosen.values())
    for slr in sorted({d['slr'] for d in device.values()}):
        capacity={r:sum(d['resources'][r] for d in device.values() if d['slr']==slr) for r in RESOURCES}
        demand={r:sum(m[r] for m in modules if chosen[m['module_id']]['slrs']==[slr]) for r in RESOURCES}
        budgets[str(slr)]=dict(capacity=capacity,demand=demand,
            utilization={r:demand[r]/capacity[r] if capacity[r] else 0 for r in RESOURCES},
            within_inherited_total_budget=all(demand[r]<=capacity[r]*prior['limits'][r]+1e-8 for r in RESOURCES))
    result=copy.deepcopy(prior)
    result.update(status='soft_envelope_ready',tag='hot_edge_empty_cr_soft_padding',regions=chosen,
        region_format='exact_CR_union',planning_regions=planning,
        components=comp,objective=prior['objective'],overlap=audit,soft_geometry=soft_geometry,
        resource_accounting=dict(schema='core-only-v1',basis='planning_regions',
            expanded_CR_resources_counted=False,expanded_CR_demand_assigned=False,
            expanded_CR_cost_evaluated=False),
        uniform_overlap_pass=audit['valid'],edge_padding=changes,slr_resource_budgets=budgets,
        soft_resource_check_role='core_only; soft_expansion_is_geometry_not_a_resource_allocation',
        core_plan='core_solution.json',core_objective=prior['objective'],
        selection=dict(reference=str(reference),tag=prior['tag'],objective=prior['objective'],
            rule='Preserve the reference J-selected core. Padding is a later export step and cannot select or move the core.'),
        soft_diagnostic_objective=None,
        total_module_crs=sum(r['area'] for r in planning.values()),
        objective_role='unchanged_J_of_selected_core; padding_not_scored',
        search_certificate='One deterministic expansion pass. No floorplan optimization or optimality claim.',
        timing_validation='Not run for this edge-padded export.',
        acceptance='Exact geometry, members and same-SLR empty-neighbor policy checked; no P&R.',
        physical_model='Capacity-weighted estimates on the selected core only. Padding is an unallocated soft allowance; actual occupancy is unknown.')
    return result,changes


def generate(run,previous):
    if previous.name=='implementation_input':previous=previous.parent
    reference=previous/'implementation_input/export/static_regions.json'
    prior=json.loads(reference.read_text())
    validate_core(prior)
    assert prior==json.loads((previous/'export/static_regions.json').read_text())
    meta=json.loads((previous/'export/modules.json').read_text())
    sources=[p for folder in ['export','implementation_input'] for p in (previous/folder).rglob('*') if p.is_file()]
    sources += [previous/n for n in ['input/cr.tsv','netmodel.pkl','directed.json','solution.json']]
    immutable={str(p):sha(p) for p in sources}
    (run/'input').mkdir(exist_ok=True)
    shutil.copytree(previous/'export',run/'input/export')
    shutil.copy2(previous/'input/cr.tsv',run/'input/cr.tsv')
    for name in ['netmodel.pkl','directed.json']:shutil.copy2(previous/name,run/name)
    shutil.copy2(reference,run/'core_solution.json')
    result,changes=build_envelope(meta['modules'],prior,load_device(run/'input/cr.tsv'),reference)
    comp=result['components'];fixed=comp['fixed_partition_cost'];audit=result['overlap'];chosen=result['regions']
    write(run/'solution.json',result);write(run/'edge_padding.json',changes)
    write(run/'comparison.json',dict(core=comp,exported_core=comp,soft_envelope=None,reason='Soft geometry is not rescored or assigned resources.'))
    shutil.copytree(run/'input/export',run/'export');write(run/'export/static_regions.json',result)
    shutil.copytree(previous/'implementation_input',run/'implementation_input')
    shutil.copy2(run/'core_solution.json',run/'implementation_input/core_solution.json')
    write(run/'implementation_input/export/static_regions.json',result)
    write(run/'implementation_input/edge_padding.json',changes)
    (run/'implementation_input/regions.tcl').write_text(regions_tcl(chosen))
    (run/'implementation_input/soft_region_adapter.tcl').write_text(geometry_adapter(run/'source/adapter_reference.tcl'))
    manifest=json.loads((run/'implementation_input/manifest.json').read_text())
    manifest.update(source=str(run/'export'),edge_padding='edge_padding.json',core_plan='core_solution.json',
        scope=f"Preserved J-selected core; all eligible modules independently add core-empty CRs under the unified {changes['policy']['threshold']:.0%} rule. Shared soft regions allowed. Core-only resource/cost accounting; expansions shown as geometry only. No RAM80 rule or whole-SLR override.")
    manifest['files']={str(p.relative_to(run/'implementation_input')):sha(p)
        for p in (run/'implementation_input').rglob('*') if p.is_file() and p.name!='manifest.json'}
    write(run/'implementation_input/manifest.json',manifest)
    write(run/'binding.json',dict(previous=str(previous),reference_core=str(reference),reference_core_sha256=sha(reference),
        core_objective=prior['objective'],input_dcp=meta['input_dcp'],input_sha256=meta['input_sha256'],
        immutable_files=immutable,fixed_partition_cost=fixed,total_leaf_cells=meta['validation']['all_cells'],
        scope='Soft export only. No partition, search, netlist edits, fanout, P&R, STA or Git.'))
    for p,h in immutable.items():assert sha(p)==h,p
    print(json.dumps(dict(stage='exported',changed=changes['changed_modules'],added_CR=changes['added_unique_crs'],
        added_module_CR=changes['added_module_crs'],shared_new_CR=changes['shared_new_crs'],
        core_J=prior['objective'],resource_basis='core_only',uniform_overlap_pass=audit['valid'])),flush=True)


if __name__=='__main__':generate(Path(sys.argv[1]).resolve(),Path(sys.argv[2]).resolve())
