"""Export resource-specific URAM soft envelopes without changing core accounting."""
import argparse
import copy
import csv
import hashlib
import json
import math
from pathlib import Path
import shutil

SOURCE=Path(__file__).resolve().parent


def load(p):return json.loads(p.read_text())
def dump(p,v):p.write_text(json.dumps(v,indent=2)+'\n')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def build(previous,output,device_path,requests):
    if output.exists():raise FileExistsError(output)
    manifest=load(previous/'manifest.json')
    for n,h in manifest['files'].items():
        p=(previous/n).resolve()
        if previous.resolve() not in p.parents or sha(p)!=h:raise ValueError('Input binding mismatch: '+n)
    core=load(previous/'core_solution.json');soft=load(previous/'export/static_regions.json')
    if soft.get('resource_soft_regions'):raise ValueError('Resource expansion already applied.')
    modules={m['module_id']:m for m in load(previous/'export/modules.json')['modules']}
    with device_path.open() as stream:
        device={r['cr']:r for r in csv.DictReader(stream,delimiter='\t')}
    additions={}
    for mid,bounds in requests.items():
        if mid not in modules or not mid.isalnum():raise ValueError('Unknown module: '+mid)
        original=core['regions'][mid];demand=modules[mid]['URAM'];capacity=original['capacity']['URAM']
        if not capacity or not math.isclose(demand/capacity,1.,abs_tol=1e-12):
            raise ValueError('Only modules at 100% core URAM are eligible: '+mid)
        if len(bounds)!=4 or any(type(v) is not int for v in bounds):raise ValueError('Invalid bounds.')
        x0,y0,x1,y1=bounds;ox0,oy0,ox1,oy1=original['bounds']
        if (x0,x1)!=(ox0,ox1) or y0>oy0 or y1<oy1:raise ValueError('URAM extension must be vertical and retain the core.')
        crs=[f'X{x}Y{y}' for x in range(x0,x1+1) for y in range(y0,y1+1)]
        if not crs or any(c not in device for c in crs):raise ValueError('Envelope outside device.')
        uram_crs=[c for c in crs if int(device[c]['URAM'])]
        existing=[c for c in soft['regions'][mid]['crs'] if int(device[c]['URAM'])]
        allowed=sorted(set(existing)|set(uram_crs));extra=sorted(set(allowed)-set(existing))
        if not extra:raise ValueError('No additional URAM sites: '+mid)
        additions[mid]=dict(URAM=dict(envelope_bounds=bounds,envelope_crs=crs,
            allowed_crs=allowed,added_crs=extra,original_core_demand=demand,original_core_capacity=capacity,
            additional_site_count=sum(int(device[c]['URAM']) for c in extra),
            allowed_site_count=sum(int(device[c]['URAM']) for c in allowed),capacity_credit=False))
    if not additions:raise ValueError('No requested extension.')
    shutil.copytree(previous,output)
    updated=copy.deepcopy(soft);updated['resource_soft_regions']=additions
    updated['resource_soft_policy']=dict(schema='uram-only-soft-v1',trigger='module_core_URAM_equals_100_percent',
        core_and_J_unchanged=True,resource_estimates_unchanged=True,soft_only=True,
        expected_site_rule='Base soft CR sites plus only URAM sites from resource-specific added CRs.')
    dump(output/'export/static_regions.json',updated)
    dump(output/'uram_soft_policy.json',dict(schema='uram-only-soft-v1',requests=requests,modules=additions,
        previous_input=str(previous),core_sha256=sha(previous/'core_solution.json'),
        validation_scope='Static export; native site checks are recorded separately.'))
    # Add only URAM sites after the original whole-module ranges are installed.
    adapter=(output/'soft_region_adapter.tcl').read_text()
    needle='    if {[bi_geometry $out/geometry_initial 1]}'
    if adapter.count(needle)!=1:raise ValueError('Unsupported application adapter.')
    adapter=adapter.replace(needle,'    bi_apply_resource_extensions $out\n'+needle)
    (output/'soft_region_adapter.tcl').write_text(adapter)
    shutil.copy2(SOURCE/'uram_resource_adapter.tcl',output/'uram_resource_adapter.tcl')
    lines=['set ::bi_resource_extra_crs [dict create]']
    for mid,entry in sorted(additions.items()):
        lines.append('dict set ::bi_resource_extra_crs '+mid+' URAM {'+' '.join(entry['URAM']['added_crs'])+'}')
    lines.append('source [file join [file dirname [info script]] uram_resource_adapter.tcl]')
    with (output/'regions.tcl').open('a') as f:f.write('\n'+'\n'.join(lines)+'\n')
    changed={'export/static_regions.json','soft_region_adapter.tcl','regions.tcl'}
    for n,h in manifest['files'].items():
        if n not in changed:assert sha(output/n)==h,n
    for key in ['regions','planning_regions','components','overlap','objective','resource_accounting']:
        if key in soft:assert updated[key]==soft[key],key
    newmanifest=dict(manifest,resource_soft_schema='uram-only-soft-v1',previous_input=str(previous),
        backend_requirement='Resource-aware site geometry and URAM-specific spill checks; use supplied compatible audit.',
        files={str(p.relative_to(output)):sha(p) for p in output.rglob('*') if p.is_file() and p.name!='manifest.json'})
    dump(output/'manifest.json',newmanifest)
    return additions


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ['previous','output','device','requests']:parser.add_argument('--'+key,type=Path,required=True)
    a=parser.parse_args();print(json.dumps(build(a.previous,a.output,a.device,load(a.requests))))
