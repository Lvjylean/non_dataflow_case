"""Export-only RAM-triggered rightward soft-Pblock padding; core plan is immutable."""
import copy
import hashlib
import json
import pickle
import shutil
import sys
from pathlib import Path
from static_regions import RESOURCES, load_device, all_rectangles, overlap_audit
from directed_model import DirectedModel
try:
    from prepare_adapter import prepare
except ModuleNotFoundError:
    sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'balanced_implementation'))
    from prepare import prepare

POLICY = dict(schema='ram-right-soft-padding-v1',ram_resources=['URAM','BRAM18'],
    threshold=0.80,comparison='strictly_greater',axis='x',direction=1,cr_columns=1,
    apply_stage='soft_pblock_export_only',boundary='clip_to_device_right_edge',
    utilization_basis='each_RAM_type_demand_over_core_region_capacity',
    capacity_limits='inherit_core_plan; threshold_is_not_a_new_capacity_limit',
    resource_scope='whole_module_clock_region_rectangle',repeat='reject_already_padded_input')

def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(8*1024*1024),b''):h.update(b)
    return h.hexdigest()

def write(path,data):path.write_text(json.dumps(data,indent=2)+'\n')

def padded_regions(modules,core,device):
    if 'soft_padding' in core:raise ValueError('Use the original core plan; padding cannot be applied twice.')
    lookup={tuple(r['bounds']):r for r in all_rectangles(device)}
    max_x=max(d['x'] for d in device.values());chosen=copy.deepcopy(core['regions']);changes=[]
    for m in modules:
        mid=m['module_id'];r=core['regions'][mid];fractions={};triggers=[]
        for res in POLICY['ram_resources']:
            demand=m.get(res,0);capacity=r['capacity'][res]
            if demand and not capacity:raise ValueError(f'{mid} {res}: demand without capacity')
            fractions[res]=demand/capacity if capacity else 0.
            # Integer arithmetic makes the strict 80% boundary exact.
            if demand*5>capacity*4:triggers.append(res)
        bounds=list(r['bounds']);status='not_triggered'
        if triggers:
            bounds[2]=min(bounds[2]+1,max_x)
            if bounds==r['bounds']:status='device_edge_no_expansion'
            elif tuple(bounds) not in lookup:status='unavailable_right_column';bounds=list(r['bounds'])
            else:status='expanded';chosen[mid]=copy.deepcopy(lookup[tuple(bounds)])
        changes.append(dict(module=mid,ram_utilization=fractions,trigger_resources=triggers,
            status=status,core_bounds=r['bounds'],soft_bounds=bounds,
            added_crs=sorted(set(chosen[mid]['crs'])-set(r['crs']))))
    return chosen,changes

def generate(run,previous):
    core=json.loads((previous/'export/static_regions.json').read_text())
    meta=json.loads((previous/'export/modules.json').read_text())
    assert len(meta['modules'])==11
    sources=[p for p in (previous/'export').iterdir() if p.is_file()]
    sources += [previous/'input/cr.tsv',previous/'netmodel.pkl',previous/'directed.json',previous/'binding.json']
    immutable={str(p):sha(p) for p in sources}
    (run/'input').mkdir(exist_ok=True);shutil.copytree(previous/'export',run/'input/export')
    shutil.copy2(previous/'input/cr.tsv',run/'input/cr.tsv')
    for name in ['netmodel.pkl','directed.json']:shutil.copy2(previous/name,run/name)
    shutil.copy2(previous/'export/static_regions.json',run/'core_solution.json')
    device=load_device(run/'input/cr.tsv')
    chosen,changes=padded_regions(meta['modules'],core,device)
    limits=core['limits'];audit=overlap_audit(meta['modules'],chosen,device,limits)
    if not audit['valid']:raise ValueError(f'Expanded-region resource audit failed: {audit["violations"]}')
    with (run/'netmodel.pkl').open('rb') as f:netmodel=pickle.load(f)
    directed=DirectedModel(json.loads((run/'directed.json').read_text()),device,core['configuration'])
    def score(regions):
        base=netmodel.components({f'P{i:02d}':regions[f'S{i:02d}'] for i in range(11)},core['configuration']['slr_distance_weight'])
        extra=directed.components(regions,True);fixed=core['components']['fixed_partition_cost']
        result=dict(base,**extra,fixed_partition_cost=fixed)
        result['old_J']=base['physical_cost']+fixed
        result['J']=result['old_J']+extra['directed_term']+extra['branch_square_term']
        return result
    before=score(core['regions'])
    assert abs(before['J']-core['objective'])<1e-6
    after=score(chosen)
    result=copy.deepcopy(core)
    result.update(tag='ram_right_soft_padding',regions=chosen,components=after,overlap=audit,
        objective=after['J'],core_objective=core['objective'],objective_role='diagnostic_rescore_of_exported_soft_envelope_not_reoptimization',
        families=directed.family_audit(chosen),total_module_crs=sum(r['area'] for r in chosen.values()),
        maximum_slrs_per_unit=max(len(r['slrs']) for r in chosen.values()),
        soft_padding=dict(policy=POLICY,changes=changes),core_plan='core_solution.json',
        search_certificate='No new search. Frozen core result with deterministic export padding; diagnostic costs are not optimized.',
        runtime_seconds=None,timing_validation='Not run for padded regions.',
        physical_model='Capacity-weighted diagnostic projection inside expanded soft regions; core optimizer unchanged.')
    write(run/'solution.json',result);shutil.copytree(run/'input/export',run/'export')
    write(run/'export/static_regions.json',result);write(run/'padding.json',result['soft_padding'])
    write(run/'comparison.json',dict(core=before,soft_envelope=after,
        core_families=core['families'],soft_families=result['families']))
    binding=dict(previous=str(previous),input_dcp=meta['input_dcp'],input_sha256=meta['input_sha256'],
        immutable_files=immutable,fixed_partition_cost=core['components']['fixed_partition_cost'],
        module_count=11,total_leaf_cells=meta['validation']['all_cells'],logical_cells=sum(m['cells'] for m in meta['modules']),
        scope='Only rightward export padding for RAM>80%; no repartition, search, fanout, STA, Vivado or DCP edits.')
    write(run/'binding.json',binding)
    manifest=prepare(run/'export',run/'implementation_input',11)
    # Keep the core reference alongside the final executable region input.
    shutil.copy2(run/'core_solution.json',run/'implementation_input/core_solution.json')
    shutil.copy2(run/'padding.json',run/'implementation_input/padding.json')
    manifest.update(core_plan='core_solution.json',soft_padding='padding.json',
        scope='Frozen memberships; regions.tcl contains final padded soft-Pblock rectangles. Core plan retained separately.')
    manifest['files']={str(p.relative_to(run/'implementation_input')):sha(p)
        for p in (run/'implementation_input').rglob('*') if p.is_file() and p.name!='manifest.json'}
    write(run/'implementation_input/manifest.json',manifest)
    for p,h in immutable.items():assert sha(p)==h,p
    print(json.dumps(dict(status='exported',changes=changes,core_J=before['J'],diagnostic_soft_J=after['J'])),flush=True)

if __name__=='__main__':generate(Path(sys.argv[1]),Path(sys.argv[2]))
