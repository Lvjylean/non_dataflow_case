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
            assert set(r['crs'])=={f'X{x}Y{y}' for x in range(x0,x1+1) for y in range(y0,y1+1)}
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
        for c,rs in occupancy.items():
            for r,v in rs.items():assert v<=(1 if r=='URAM' else .7)+1e-8,(c,r,v)
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
        result.update(raw_boundary_histogram=dict(hist),families=family,peak_utilization={r:max(o[r] for o in occupancy.values()) for r in RESOURCES})
        return result
    core=load('core_solution.json')
    independent=dict(core=arithmetic(core),soft_envelope=arithmetic(solution))
    assert sha(run/'core_solution.json')==sha(run/'input/export/static_regions.json')
    by_id={m['module_id']:m for m in modules};events={e['module']:e for e in load('padding.json')['changes']}
    max_x=max(d['x'] for d in device.values())
    changed=[];edge=[]
    for mid,r in core['regions'].items():
        demand=by_id[mid]
        triggered=any(demand[res]*5>r['capacity'][res]*4 for res in ('URAM','BRAM18'))
        expected=list(r['bounds'])
        if triggered:expected[2]=min(expected[2]+1,max_x)
        assert solution['regions'][mid]['bounds']==expected,(mid,expected)
        assert solution['regions'][mid]['slrs']==r['slrs']
        assert set(r['crs']).issubset(solution['regions'][mid]['crs'])
        if expected!=r['bounds']:changed.append(mid)
        elif triggered:edge.append(mid)
        assert bool(events[mid]['trigger_resources'])==triggered
    assert changed==['S02','S03','S10'] and edge==['S04'],(changed,edge)
    import subprocess
    script='source {'+str(run/'implementation_input/regions.tcl')+'}\n'
    script+='dict for {m b} $planned_bounds {puts "$m|$b|[join [dict get $planned_regions $m] ,]"}\n'
    native=subprocess.run(['tclsh'],input=script,text=True,capture_output=True,check=True)
    parsed={}
    for line in native.stdout.splitlines():
        mid,b,crs=line.split('|');parsed[mid]=list(map(int,b.split()))
        assert set(crs.split(','))==set(solution['regions'][mid]['crs'])
    assert parsed=={m:r['bounds'] for m,r in solution['regions'].items()}
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
        padding_changed=changed,padding_edge_clipped=edge,tcl_regions_loaded=True,membership_byte_identical=True,
        method='Independent CR-pair enumeration for directed branches, probability products for hypernet spans, direct resource/geometry checks. No optimizer scoring methods reused.')
    (run/'verification.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(stage='verified',status='PASS',J=independent['soft_envelope']['J'])),flush=True)

if __name__=='__main__':verify(Path(sys.argv[1]))
