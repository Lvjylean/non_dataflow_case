"""Independent CR-pair arithmetic, resource geometry, immutable-export verification."""
import csv
import hashlib
import json
import pickle
import sys
from collections import Counter
from pathlib import Path
from static_regions import RESOURCES

def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(8*1024*1024),b''):h.update(b)
    return h.hexdigest()

def verify(run):
    load=lambda p:json.loads((run/p).read_text())
    solution=load('solution.json');data=load('directed.json');cfg=solution['configuration']
    modules=load('input/export/modules.json')['modules'];binding=load('binding.json')
    with (run/'netmodel.pkl').open('rb') as f:netmodel=pickle.load(f)
    device={}
    for row in csv.DictReader((run/'input/cr.tsv').open(),delimiter='\t'):
        n=int(row['SLICEL'])+int(row['SLICEM']);sm=int(row['SLICEM'])
        device[row['cr']]=dict(x=int(row['x']),y=int(row['y']),slr=int(row['slr'][3:]),
            capacity=dict(LUT=8*n,FF=16*n,DSP=int(row['DSP']),BRAM18=2*int(row['BRAM36']),URAM=int(row['URAM']),LUTMEM=8*sm,CARRY8=n,MUXF7=4*n,MUXF8=2*n))
    axes=[(a,t) for a in ['x','y','slr'] for t in range(max(d[a] for d in device.values()))]
    def arithmetic(plan):
        chosen=plan['regions'];profile={};cdf={};occupancy={c:Counter() for c in device}
        for i,m in enumerate(modules):
            mid=m['module_id'];r=chosen[mid];x0,y0,x1,y1=r['bounds']
            assert len(r['crs'])==len(set(r['crs'])) and set(r['crs'])<=set(device)
            assert [min(device[c]['x'] for c in r['crs']),min(device[c]['y'] for c in r['crs']),max(device[c]['x'] for c in r['crs']),max(device[c]['y'] for c in r['crs'])]==r['bounds']
            assert r['area']==len(r['crs'])
            # Export padding is not limited by the core search area window.
            for ri,res in enumerate(RESOURCES):
                cap=sum(device[c]['capacity'][res] for c in r['crs']);assert cap==r['capacity'][res]
                assert m[res]<=cap*(1 if res=='URAM' else .7)+1e-8
                if not cap:continue
                slot=i*len(RESOURCES)+ri
                profile[slot]=[(device[c],device[c]['capacity'][res]/cap) for c in r['crs'] if device[c]['capacity'][res]]
                cdf[slot]=[sum(p for loc,p in profile[slot] if loc[a]<=t) for a,t in axes]
                for c in r['crs']:
                    if device[c]['capacity'][res]:occupancy[c][res]+=m[res]/cap
        uniform_violations=[dict(cr=c,resource=r,utilization=v,limit=(1 if r=='URAM' else .7)) for c,rs in occupancy.items() for r,v in rs.items() if v>(1 if r=='URAM' else .7)+1e-6]
        spans=Counter()
        for pattern,weight in zip(netmodel.patterns,netmodel.weights):
            for t,(axis,_) in enumerate(axes):
                left=right=1.
                for slot,count in pattern:
                    value=cdf[slot][t];left*=value**count;right*=(1-value)**count
                spans[axis]+=float(weight)*max(0,1-left-right)
        values=Counter();hist=Counter();family={}
        pair_cache={}
        def pair(a,b):
            if (a,b) not in pair_cache:
                sums=Counter();hs=Counter()
                for la,pa in profile[a]:
                    for lb,pb in profile[b]:
                        mass=pa*pb;ds=abs(la['slr']-lb['slr'])
                        sums['x']+=mass*abs(la['x']-lb['x']);sums['y']+=mass*abs(la['y']-lb['y'])
                        sums['slr']+=mass*ds;sums['square']+=mass*max(0,ds-1)**2;hs[ds]+=mass
                pair_cache[a,b]=sums,hs
            return pair_cache[a,b]
        for e in data['pairs']:
            sums,hs=pair(e['source'],e['sink'])
            for k,v in sums.items():values[k]+=e['weight']*v
            for k,v in hs.items():hist[k]+=e['pins']*v
        hist[0]+=data['coverage']['same_atom_pins']
        for name,f in data['families'].items():
            hs=Counter({0:f['same_atom_pins']})
            for e in f['pairs']:
                _,ph=pair(e['source'],e['sink'])
                for k,v in ph.items():hs[k]+=e['pins']*v
            family[name]=dict(histogram=dict(hs),far_sink_pins=sum(v for k,v in hs.items() if k>1))
            assert abs(family[name]['far_sink_pins']-plan['families'][name]['far_sink_pins'])<1e-6
        physical=spans['x']+spans['y']+cfg['slr_distance_weight']*spans['slr']
        direct=values['x']+values['y']+cfg['slr_distance_weight']*values['slr']
        result=dict(physical_cost=physical,directed_distance=direct,branch_square=values['square'],
            raw_far_pins=sum(v for k,v in hist.items() if k>1),raw_branch_boundaries=sum(k*v for k,v in hist.items()),
            J=physical+binding['fixed_partition_cost']+cfg['directed_weight']*direct+cfg['branch_square_weight']*values['square'])
        for k,v in result.items():assert abs(v-plan['components'][k])<max(1e-6,abs(v)*1e-10),(k,v,plan['components'][k])
        assert abs(sum(hist.values())-data['coverage']['modeled_sink_pins'])<1e-6
        result.update(uniform_violations=uniform_violations,raw_boundary_histogram=dict(hist),families=family,peak_utilization={r:max(o[r] for o in occupancy.values()) for r in RESOURCES})
        return result
    previous=load('input/export/static_regions.json')
    assert sha(run/'core_solution.json')==sha(Path(binding['reference_core']))==binding['reference_core_sha256']
    assert sha(run/'implementation_input/core_solution.json')==binding['reference_core_sha256']
    assert load('core_solution.json')==previous
    assert previous['status']=='feasible' and previous['overlap']['valid']
    assert all(k not in previous and k not in solution for k in ['soft_padding','soft_override'])
    assert solution['configuration']==previous['configuration'] and solution['limits']==previous['limits']
    assert solution['core_objective']==solution['selection']['objective']==previous['objective']
    assert solution['soft_diagnostic_objective'] is None
    assert solution['planning_regions']==previous['regions']
    for key in ['components','objective','overlap','families','total_module_crs']:
        assert solution[key]==previous[key],key
    assert solution['resource_accounting']==dict(schema='core-only-v1',basis='planning_regions',
        expanded_CR_resources_counted=False,expanded_CR_demand_assigned=False,expanded_CR_cost_evaluated=False)
    independent=dict(core=arithmetic(previous),soft_envelope=None)
    for mid,r in solution['regions'].items():
        assert 'capacity' not in r and r['geometry_role']=='soft_allowance_only'
        assert len(r['crs'])==len(set(r['crs'])) and set(r['crs'])<=set(device)
        assert r['area']==len(r['crs'])
        assert r['core_crs']==previous['regions'][mid]['crs']
        assert set(r['padding_crs'])==set(r['crs'])-set(r['core_crs'])
        assert r['bounds']==[min(device[c]['x'] for c in r['crs']),min(device[c]['y'] for c in r['crs']),max(device[c]['x'] for c in r['crs']),max(device[c]['y'] for c in r['crs'])]
    covers=Counter(c for r in solution['regions'].values() for c in r['crs'])
    assert solution['soft_geometry']==dict(total_module_crs=sum(covers.values()),occupied_crs=len(covers),overlapping_crs=sum(v>1 for v in covers.values()))
    assert solution['status']=='soft_envelope_ready'
    from fractions import Fraction
    threshold=Fraction(str(solution['edge_padding']['policy']['threshold']))
    before={mid:set(r['crs']) for mid,r in previous['regions'].items()}
    occupied=set().union(*before.values())
    # Independent target-centric enumeration, rather than the generator's edge walk.
    eligible={}
    for target,td in device.items():
        if target in occupied:continue
        for mid,crs in before.items():
            for source in crs:
                sd=device[source]
                if td['slr']!=sd['slr'] or abs(td['x']-sd['x'])+abs(td['y']-sd['y'])!=1:continue
                pressure={r:sum((Fraction(m[r],previous['regions'][m['module_id']]['capacity'][r])
                    for m in modules if source in before[m['module_id']] and m[r] and sd['capacity'][r]),Fraction(0)) for r in RESOURCES}
                peak=max(pressure.values())
                if peak>threshold:eligible.setdefault(target,[]).append((peak,mid,source))
    expected={mid:set(crs) for mid,crs in before.items()}
    for target,options in eligible.items():
        for mid in {mid for _,mid,_ in options}:expected[mid].add(target)
    assert expected=={mid:set(r['crs']) for mid,r in solution['regions'].items()}
    changed=[m for m in before if expected[m]!=before[m]]
    assert changed==solution['edge_padding']['changed_modules']
    additions=sum(len(expected[m]-before[m]) for m in before)
    assert additions==solution['edge_padding']['added_module_crs']
    assert len(eligible)==solution['edge_padding']['added_unique_crs']
    sharing={c:sorted({mid for _,mid,_ in options}) for c,options in eligible.items()}
    assert {c['cr']:c['modules'] for c in solution['edge_padding']['claims']}==sharing
    assert sum(len(ms)>1 for ms in sharing.values())==solution['edge_padding']['shared_new_crs']
    assert solution['edge_padding']['policy']['schema']=='hot-edge-empty-cr-v2-shared'
    for change in solution['edge_padding']['changes']:
        mid=change['module']
        assert set(change['added_crs'])==expected[mid]-before[mid]
        assert set(change['shared_added_crs'])=={c for c,ms in sharing.items() if mid in ms and len(ms)>1}
    assert all(solution['regions'][m]['slrs']==previous['regions'][m]['slrs'] for m in before)
    assert bool(independent['core']['uniform_violations'])==bool(solution['overlap']['violations'])
    assert solution['uniform_overlap_pass']==(not independent['core']['uniform_violations'])
    assert solution['soft_resource_check_role'].startswith('core_only')
    import gzip
    counts=Counter();resources={m['module_id']:Counter() for m in modules};names=set()
    with gzip.open(run/'export/leaf_cells.tsv.gz','rt') as f:
        for i,row in enumerate(csv.DictReader(f,delimiter='\t')):
            assert row['cell_id']==f'c{i}' and row['cell_name'] not in names
            names.add(row['cell_name']);mid=row['module_id'];counts[mid]+=1
            if mid in resources:resources[mid].update({r:int(row[r]) for r in RESOURCES})
    assert len(names)==binding['total_leaf_cells']
    for m in modules:
        assert counts[m['module_id']]==m['cells']
        assert all(resources[m['module_id']][r]==m[r] for r in RESOURCES)
    assert counts['CONSTANT']==25800 and counts['CLOCK']==1
    for slr in range(4):
        for r in RESOURCES:
            capacity=sum(d['capacity'][r] for d in device.values() if d['slr']==slr)
            demand=sum(m[r] for m in modules if solution['regions'][m['module_id']]['slrs']==[slr])
            assert demand<=capacity*solution['limits'][r]+1e-8
            assert demand==solution['slr_resource_budgets'][str(slr)]['demand'][r]
    import subprocess
    script='source {'+str(run/'implementation_input/regions.tcl')+'}\n'
    script+='dict for {m b} $planned_bounds {puts "$m|$b|[join [dict get $planned_regions $m] ,]"}\n'
    native=subprocess.run(['tclsh'],input=script,text=True,capture_output=True,check=True)
    parsed={}
    for line in native.stdout.splitlines():
        mid,b,crs=line.split('|');parsed[mid]=list(map(int,b.split()))
        assert set(crs.split(','))==set(solution['regions'][mid]['crs'])
    assert not native.stderr,native.stderr
    assert parsed=={m:r['bounds'] for m,r in solution['regions'].items()}
    assert (run/'implementation_input/soft_region_adapter.tcl').read_text().count('proc bi_apply ')==1
    assert not (run/'implementation_input/padding.json').exists()
    assert not (run/'implementation_input/override.json').exists()
    assert sha(run/'implementation_input/membership.tsv')==sha(Path(binding['previous'])/'implementation_input/membership.tsv')
    for n,h in load('implementation_input/manifest.json')['files'].items():assert sha(run/'implementation_input'/n)==h,n
    for p,h in binding['immutable_files'].items():assert sha(Path(p))==h,p
    assert sha(Path(binding['input_dcp']))==binding['input_sha256']
    members={}
    for p in (run/'input/export').iterdir():
        if p.is_file() and p.name!='static_regions.json':
            h=sha(p);assert sha(run/'export'/p.name)==h;members[p.name]=h
    for n,h in load('source/manifest.json').items():assert sha(run/'source'/n)==h,n
    result=dict(status='PASS',independent=independent,unchanged_export_files=members,
        immutable_input_count=len(binding['immutable_files']),source_manifest_verified=True,input_dcp_sha256_verified=True,
        changed_modules=changed,leaf_cells=len(names),core_byte_identical=True,core_selection_J_unchanged=True,
        resource_accounting_core_only=True,soft_resources_and_cost_not_evaluated=True,
        legacy_RAM80_rule_absent=True,whole_SLR_override_absent=True,
        shared_expansion_checked=True,added_module_CR=additions,shared_new_CR=sum(len(ms)>1 for ms in sharing.values()),
        slr_total_budgets_pass=True,uniform_overlap_pass=solution['overlap']['valid'],edge_rule_checked=True,added_CR=len(eligible),tcl_regions_loaded=True,membership_byte_identical=True,
        method='Independent CR-pair enumeration for directed branches, probability products for hypernet spans, direct resource/geometry checks. No optimizer scoring methods reused.')
    (run/'verification.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(stage='verified',status='PASS',J=independent['core']['J'])),flush=True)

if __name__=='__main__':verify(Path(sys.argv[1]))
