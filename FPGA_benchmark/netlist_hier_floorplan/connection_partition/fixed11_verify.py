"""Independent CR-pair arithmetic, resource geometry, immutable-export verification."""
import csv
import hashlib
import json
import pickle
import sys
from collections import Counter
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]).resolve()/'source'))
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
    path_graph=None
    if cfg.get('cumulative_paths',{}).get('enabled',False):
        from cumulative_paths import settings, independent_score
        from path_cache import read
        path_cfg=settings(cfg);path_graph=read(run)
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
            assert sorted({device[c]['slr'] for c in r['crs']})==r['slrs']
            within_window=r['area']<=solution['candidate_stats'][mid]['minimum_crs']*cfg['region_max_area_factor']+cfg['region_max_area_extra_crs']
            inherited=cfg.get('inherited_parent_regions',{}).get(mid)
            assert within_window or (isinstance(inherited,list) and r['bounds']==inherited)
            if not within_window:
                assert solution['candidate_stats'][mid]['inherited_parent_bounds']==inherited
            for ri,res in enumerate(RESOURCES):
                cap=sum(device[c]['capacity'][res] for c in r['crs']);assert cap==r['capacity'][res]
                assert m[res]<=cap*solution['limits'][res]+1e-8
                if not cap:continue
                slot=i*len(RESOURCES)+ri
                profile[slot]=[(device[c],device[c]['capacity'][res]/cap) for c in r['crs'] if device[c]['capacity'][res]]
                cdf[slot]=[sum(p for loc,p in profile[slot] if loc[a]<=t) for a,t in axes]
                for c in r['crs']:
                    if device[c]['capacity'][res]:occupancy[c][res]+=m[res]/cap
        for c,rs in occupancy.items():
            for r,v in rs.items():assert v<=solution['limits'][r]+1e-8,(c,r,v)
        spans=Counter()
        legacy_patterns = [] if getattr(netmodel,'schema',None)=='boundary_spatial_v1' else zip(netmodel.patterns,netmodel.weights)
        for pattern,weight in legacy_patterns:
            for t,(axis,_) in enumerate(axes):
                left=right=1.
                for slot,count in pattern:
                    value=cdf[slot][t];left*=value**count;right*=(1-value)**count
                spans[axis]+=float(weight)*max(0,1-left-right)
        if getattr(netmodel,'schema',None)=='boundary_spatial_v1':
            from boundary_hyper import independent_spans
            spans.update(independent_spans(netmodel,{f'P{i:02d}':chosen[m['module_id']] for i,m in enumerate(modules)}))
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
        from boundary_directed import selection, SCHEMA, independent_components
        spatial={}
        if selection(cfg)==SCHEMA:
            spatial=independent_components(data['spatial'],chosen,
                {c:dict(d,resources=d['capacity']) for c,d in device.items()},cfg,
                [m['module_id'] for m in modules])
            direct=spatial['directed_distance']
        hypernet_term=cfg.get('hypernet_weight',1.)*physical
        result=dict(physical_cost=physical,directed_distance=direct,branch_square=values['square'],
            raw_far_pins=sum(v for k,v in hist.items() if k>1),raw_branch_boundaries=sum(k*v for k,v in hist.items()),
            J=hypernet_term+binding['fixed_partition_cost']+cfg['directed_weight']*direct+cfg['branch_square_weight']*values['square'])
        if 'hypernet_weight' in cfg or 'hypernet_term' in plan['components']:
            result['hypernet_term']=hypernet_term
        result.update(spatial)
        if path_graph is not None:
            path=independent_score(path_graph,chosen,path_cfg)
            result['J']+=path['cumulative_path_term']
            histogram=path.pop('cumulative_path_endpoint_histogram')
            assert {str(k):v for k,v in histogram.items()}==plan['components']['cumulative_path_endpoint_histogram']
            result.update(path)
        for k,v in result.items():assert abs(v-plan['components'][k])<max(1e-6,abs(v)*1e-10),(k,v,plan['components'][k])
        assert abs(sum(hist.values())-data['coverage']['modeled_sink_pins'])<1e-6
        result.update(raw_boundary_histogram=dict(hist),families=family,peak_utilization={r:max(o[r] for o in occupancy.values()) for r in RESOURCES})
        return result
    independent={'selected':arithmetic(solution)}
    for name in ['all_whole_die_reference_assignments','refined_whole_die']:
        if (run/'candidates'/(name+'.json')).exists():independent[name]=arithmetic(load('candidates/'+name+'.json'))
    assert all(independent['selected']['J']<=v['J']+1e-6 for v in independent.values())
    local=json.loads((run/'local_binding.json').read_text())
    for p,h in local['source_sha256'].items():assert sha(run/p)==h,p
    assert sha(run/'netmodel.pkl')==local['source_sha256']['netmodel.pkl']
    assert sha(run/'directed.json')==local['source_sha256']['directed.json']
    members={}
    for p in (run/'input/export').iterdir():
        if p.is_file() and p.name!='static_regions.json':
            h=sha(p);assert sha(run/'export'/p.name)==h;members[p.name]=h
    for n,h in load('source/manifest.json').items():assert sha(run/'source'/n)==h,n
    result=dict(status='PASS',independent=independent,unchanged_export_files=members,
        immutable_input_count=len(local['source_sha256']),source_manifest_verified=True,
        input_dcp_sha256_verified=False,original_cache_hash_verified=True,remote_accessed=False,
        cumulative_paths_verified=path_graph is not None,
        method='Independent CR-pair enumeration, hypernet probability products, scalar register-bounded propagation and resource/geometry checks. No optimizer scoring methods reused.')
    (run/'verification.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(stage='verified',status='PASS',J=independent['selected']['J'])),flush=True)

if __name__=='__main__':verify(Path(sys.argv[1]))
