"""Independent soft expansion into core-empty CRs; new regions may overlap."""
import copy
from fractions import Fraction
from static_regions import RESOURCES


POLICY = dict(schema='hot-edge-empty-cr-v2-shared', threshold=0.5, comparison='strictly_greater',
    utilization_basis='sum_of_all_module_projections_in_the_edge_CR',
    empty='no_module_core_region_contains_the_CR',
    adjacency='four_edge_neighbors_only', same_slr=True, passes=1,
    sharing='every_eligible_module_adds_the_same_core_empty_CR_independently',
    repeat='reject_already_edge_padded_input', stage='soft_constraint_export_only',
    geometry='exact_CR_union_no_bounding_box_fill',
    capacity_limits='unchanged; the threshold is an expansion trigger, not a density limit')


def region_from_crs(crs, device):
    crs=sorted(set(crs), key=lambda c:(device[c]['x'], device[c]['y']))
    if not crs: raise ValueError('Empty module region')
    xs=[device[c]['x'] for c in crs]; ys=[device[c]['y'] for c in crs]
    slrs=sorted({device[c]['slr'] for c in crs})
    bounds=[min(xs),min(ys),max(xs),max(ys)]
    return dict(crs=crs, bounds=bounds, area=len(crs), slrs=slrs,
        center=[sum(xs)/len(crs),sum(ys)/len(crs)],
        slr_center=sum(device[c]['slr'] for c in crs)/len(crs),
        capacity={r:sum(device[c]['resources'][r] for c in crs) for r in RESOURCES},
        shape='rectangle' if len(crs)==(bounds[2]-bounds[0]+1)*(bounds[3]-bounds[1]+1) else 'CR_union')


def expand(modules, plan, device):
    if 'edge_padding' in plan: raise ValueError('Use the pre-expansion plan; repeated padding is rejected.')
    threshold=Fraction(str(POLICY['threshold']))
    regions=plan['regions']; own={m:set(r['crs']) for m,r in regions.items()}
    xy={(d['x'],d['y']):c for c,d in device.items()}
    occupied=set().union(*own.values())
    pressure={c:{r:Fraction(0) for r in RESOURCES} for c in device}
    for m in modules:
        region=regions[m['module_id']]
        for c in region['crs']:
            for r in RESOURCES:
                if device[c]['resources'][r] and m.get(r,0):
                    pressure[c][r]+=Fraction(m[r],region['capacity'][r])
    candidates={}; records={}; offsets=[(-1,0,'left'),(1,0,'right'),(0,-1,'down'),(0,1,'up')]
    for mid,crs in sorted(own.items()):
        edges=[]
        for c in sorted(crs):
            loc=device[c]
            neighbors=[(xy.get((loc['x']+dx,loc['y']+dy)),direction) for dx,dy,direction in offsets]
            neighbors=[(n,d) for n,d in neighbors if n not in crs]
            if not neighbors: continue
            peak=max(pressure[c].values()); triggers=[r for r in RESOURCES if pressure[c][r]>threshold]
            entry=dict(cr=c,peak=float(peak),resources={r:float(v) for r,v in pressure[c].items()},
                       trigger_resources=triggers,neighbors=[])
            for n,direction in neighbors:
                reason=('below_or_equal_threshold' if not triggers else
                        'device_edge' if n is None else
                        'different_SLR' if device[n]['slr']!=loc['slr'] else
                        'occupied' if n in occupied else 'candidate')
                entry['neighbors'].append(dict(cr=n,direction=direction,status=reason))
                if reason=='candidate': candidates.setdefault(n,[]).append((peak,mid,c))
            edges.append(entry)
        records[mid]=dict(module=mid,before_crs=sorted(crs),edges=edges,added_crs=[],shared_added_crs=[])
    claims=[]
    for c,offers in sorted(candidates.items()):
        eligible_modules=sorted({mid for _,mid,_ in offers})
        for mid in eligible_modules:
            records[mid]['added_crs'].append(c)
            if len(eligible_modules)>1:records[mid]['shared_added_crs'].append(c)
        claims.append(dict(cr=c,modules=eligible_modules,
            evidence=[dict(module=mid,edge=edge,peak=float(peak))
                      for peak,mid,edge in sorted(offers,key=lambda v:(v[1],v[2]))]))
    chosen=copy.deepcopy(regions)
    for mid,record in records.items():
        if record['added_crs']: chosen[mid]=region_from_crs(own[mid]|set(record['added_crs']),device)
        record.update(after_crs=chosen[mid]['crs'],before_bounds=regions[mid]['bounds'],
                      after_bounds=chosen[mid]['bounds'],status='expanded' if record['added_crs'] else 'unchanged')
    return chosen,dict(policy=POLICY,changes=list(records.values()),claims=claims,
        initially_empty_crs=sorted(set(device)-occupied),
        added_unique_crs=len(claims),added_module_crs=sum(len(c['modules']) for c in claims),
        shared_new_crs=sum(len(c['modules'])>1 for c in claims),
        changed_modules=[mid for mid,r in records.items() if r['added_crs']])


def regions_tcl(regions):
    lines=['# Load only the exact-CR Pblock application procedures bundled with this input.',
           'source [file join [file dirname [info script]] soft_region_adapter.tcl]',
           'set planned_regions [dict create]','set planned_bounds [dict create]']
    for mid,r in sorted(regions.items()):
        if not mid.isalnum(): raise ValueError('Unsafe module identifier')
        lines.extend([f'dict set planned_regions {mid} {{{" ".join(r["crs"])}}}',
                      f'dict set planned_bounds {mid} {{{" ".join(map(str,r["bounds"]))}}}'])
    return '\n'.join(lines)+'\n'


def geometry_adapter(path):
    text=path.read_text()
    # Freeze only geometry application; keep the caller's fanout/protection code.
    return text[text.index('proc bi_ranges '):text.index('proc bi_geometry ')].rstrip()+'\n'
