"""Fresh-process independent arithmetic and unchanged-input verification."""
import csv
import hashlib
import itertools
import json
import math
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
    solution=json.loads((run/'solution.json').read_text())
    original=json.loads((run/'input/export/static_regions.json').read_text())
    feedback=json.loads((run/'feedback.json').read_text())
    modules=json.loads((run/'input/export/modules.json').read_text())['modules']
    binding=json.loads((run/'binding.json').read_text());cfg=solution['configuration']
    with (run/'netmodel.pkl').open('rb') as f:netmodel=pickle.load(f)
    device={}
    for row in csv.DictReader((run/'input/cr.tsv').open(),delimiter='\t'):
        n=int(row['SLICEL'])+int(row['SLICEM']);sm=int(row['SLICEM'])
        device[row['cr']]=dict(x=int(row['x']),y=int(row['y']),slr=int(row['slr'][3:]),
            capacity=dict(LUT=8*n,FF=16*n,DSP=int(row['DSP']),BRAM18=2*int(row['BRAM36']),URAM=int(row['URAM']),
                          LUTMEM=8*sm,CARRY8=n,MUXF7=4*n,MUXF8=2*n))
    axes=[(axis,t) for axis in ['x','y','slr'] for t in range(max(d[axis] for d in device.values()))]
    def arithmetic(plan):
        chosen=plan['regions'];profile={};slrs={};cdf={}
        occupancy={c:Counter() for c in device}
        for m in modules:
            mid=m['module_id'];r=chosen[mid];x0,y0,x1,y1=r['bounds']
            assert set(r['crs'])=={f'X{x}Y{y}' for x in range(x0,x1+1) for y in range(y0,y1+1)}
            for resource in RESOURCES:
                cap=sum(device[c]['capacity'][resource] for c in r['crs'])
                assert cap==r['capacity'][resource]
                assert m[resource]<=cap*(1. if resource=='URAM' else .7)+1e-8
                if not cap:continue
                profile[mid,resource]=[(device[c],device[c]['capacity'][resource]/cap) for c in r['crs'] if device[c]['capacity'][resource]]
                slrs[mid,resource]=Counter()
                for loc,p in profile[mid,resource]:slrs[mid,resource][loc['slr']]+=p
                cdf[mid,resource]=[sum(p for loc,p in profile[mid,resource] if loc[a]<=t) for a,t in axes]
                for c in r['crs']:
                    if device[c]['capacity'][resource]:occupancy[c][resource]+=m[resource]/cap
        for c,resources in occupancy.items():
            for r,value in resources.items():assert value<=(1. if r=='URAM' else .7)+1e-8,(c,r,value)
        base=Counter()
        for pattern,weight in zip(netmodel.patterns,netmodel.weights):
            for t,(axis,_) in enumerate(axes):
                left=right=1.
                for slot,count in pattern:
                    mid=f'S{slot//len(RESOURCES):02d}';r=RESOURCES[slot%len(RESOURCES)]
                    value=cdf[mid,r][t];left*=value**count;right*=(1-value)**count
                base[axis]+=float(weight)*max(0.,1-left-right)
        distance=0.;dist_cache={}
        for edge in feedback['connections']:
            a,b=[feedback['nodes'][str(edge[k])] for k in ['source','sink']]
            roles=(a['module'],a['resource'],b['module'],b['resource'])
            if roles not in dist_cache:
                d=0.
                for la,pa in profile[roles[:2]]:
                    for lb,pb in profile[roles[2:]]:
                        d+=pa*pb*(abs(la['x']-lb['x'])+abs(la['y']-lb['y'])+cfg['slr_distance_weight']*abs(la['slr']-lb['slr']))
                dist_cache[roles]=d
            distance+=edge['criticality']*dist_cache[roles]
        penalty=0.;hist_total=Counter();cache={}
        for path in feedback['paths']:
            ids=list(dict.fromkeys(path['atoms']));index={a:i for i,a in enumerate(ids)}
            probs=[]
            for a in ids:
                n=feedback['nodes'][str(a)];probs.append(sorted(slrs[n['module'],n['resource']].items()))
            key=(tuple(tuple(p) for p in probs),tuple(index[a] for a in path['atoms']))
            if key not in cache:
                assert math.prod(map(len,probs))<=1_000_000,'Enumeration coverage limit exceeded'
                hist=Counter()
                for assignment in itertools.product(*probs):
                    mass=math.prod(p for _,p in assignment)
                    loc=[assignment[index[a]][0] for a in path['atoms']]
                    n=sum(abs(a-b) for a,b in zip(loc,loc[1:]));hist[n]+=mass
                cache[key]=hist
            hist=cache[key]
            penalty+=path['criticality']*sum(mass*max(0,n-1)**2 for n,mass in hist.items())
            hist_total.update(hist)
        physical=base['x']+base['y']+cfg['slr_distance_weight']*base['slr']
        fixed=original['objective']-original['components']['physical_cost']
        result=dict(physical_cost=physical,critical_connection_distance=distance,weighted_path_square=penalty,
                    old_J=physical+fixed,J=physical+fixed+cfg['critical_distance_weight']*distance+cfg['path_square_weight']*penalty,
                    path_expected_boundaries=sum(n*v for n,v in hist_total.items()),
                    path_expected_over_one=sum(v for n,v in hist_total.items() if n>1),path_histogram=dict(hist_total))
        for k in ['physical_cost','critical_connection_distance','weighted_path_square','old_J','J','path_expected_boundaries','path_expected_over_one']:
            expected=plan['components'][k]
            assert abs(result[k]-expected)<max(1e-6,abs(expected)*1e-10),(k,result[k],expected)
        return result
    baseline=json.loads((run/'candidates/baseline.json').read_text())
    independently=dict(baseline=arithmetic(baseline),selected=arithmetic(solution))
    assert independently['selected']['J']<=independently['baseline']['J']+1e-6
    unchanged={}
    for path,expected in binding['immutable_files'].items():
        assert sha(Path(path))==expected,path
        unchanged[path]=expected
    member_files={}
    for path in sorted((run/'input/export').iterdir()):
        if path.is_file() and path.name!='static_regions.json':
            assert sha(path)==sha(run/'export'/path.name),path
            member_files[path.name]=sha(path)
    for name,expected in json.loads((run/'source/manifest.json').read_text()).items():
        assert sha(run/'source'/name)==expected,name
    result=dict(status='PASS',independent=independently,immutable_inputs=len(unchanged),
        unchanged_export_files=member_files,original_source_sha256_verified=True,
        explanation='Independent products for hypernet spans, explicit CR-pair distance sums and full discrete path enumeration; no reuse of optimizer scoring functions.')
    (run/'verification.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(stage='verified',status='PASS',unchanged_inputs=len(unchanged),selected_J=independently['selected']['J'])),flush=True)


if __name__=='__main__':verify(Path(sys.argv[1]))
