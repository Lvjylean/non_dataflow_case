"""Raw critical-connection and same-cycle path costs on fixed physical atoms."""
import itertools
from collections import Counter

import numpy as np

from balanced_physical import cdf_table
from static_regions import RESOURCES


def criticality(slack, cfg):
    fraction=max(0., min(1., 1.-slack/cfg['criticality_window_ns']))
    return cfg['criticality_floor']+(cfg['criticality_ceiling']-cfg['criticality_floor'])*fraction


def crossing_distribution(probabilities, aliases=None):
    """Exact sum-of-boundaries distribution, retaining repeated-atom correlation."""
    aliases=list(range(len(probabilities))) if aliases is None else aliases
    repeated=sorted(a for a,n in Counter(aliases).items() if n>1)
    track={a:i for i,a in enumerate(repeated)}
    states={(None,0,(-1,)*len(track)):1.}
    for probability,alias in zip(probabilities,aliases):
        updated={}
        for (last,n,assigned),mass in states.items():
            fixed=assigned[track[alias]] if alias in track else -1
            choices=[(fixed,1.)] if fixed>=0 else enumerate(probability)
            for slr,p in choices:
                if p<=1e-14: continue
                values=assigned
                if alias in track and fixed<0:
                    values=list(assigned);values[track[alias]]=slr;values=tuple(values)
                key=(slr,n+(abs(slr-last) if last is not None else 0),values)
                updated[key]=updated.get(key,0.)+mass*p
        states=updated
    hist=Counter()
    for (_,n,_),mass in states.items():hist[n]+=mass
    assert abs(sum(hist.values())-1.)<1e-8
    return dict(hist)


def positive_square(hist):
    return sum(p*max(0,n-1)**2 for n,p in hist.items())


class CriticalModel:
    def __init__(self, feedback, device, cfg):
        self.feedback=feedback;self.device=device;self.cfg=cfg
        self.dimensions=[max(d[key] for d in device.values()) for key in ('x','y','slr')]
        self.cache={};self.path_cache={}
        self.edges=Counter()
        for edge in feedback['connections']:
            a,b=feedback['nodes'][str(edge['source'])],feedback['nodes'][str(edge['sink'])]
            self.edges[(a['module'],a['resource'],b['module'],b['resource'])]+=edge['criticality']
        self.paths=Counter();self.path_counts=Counter()
        for p in feedback['paths']:
            roles=[];aliases={}
            for a in p['atoms']:
                n=feedback['nodes'][str(a)]
                roles.append((n['module'],n['resource'],aliases.setdefault(a,len(aliases))))
            roles=tuple(roles);self.paths[roles]+=p['criticality'];self.path_counts[roles]+=1

    def profile(self, region, resource):
        key=(tuple(region['bounds']),resource)
        if key not in self.cache:
            n0,n1,n2=self.dimensions
            cdf=cdf_table(region,self.device)[RESOURCES.index(resource)]
            assert region['capacity'][resource]>0
            slr=np.diff(np.r_[0.,cdf[n0+n1:],1.]);slr=np.clip(slr,0.,1.)
            self.cache[key]=(cdf,slr)
        return self.cache[key]

    def role_distance(self, a, b, chosen):
        fa,_=self.profile(chosen[a[0]],a[1]);fb,_=self.profile(chosen[b[0]],b[1])
        distance=fa*(1-fb)+fb*(1-fa)
        x,y,_=self.dimensions
        return float(distance[:x+y].sum()+self.cfg['slr_distance_weight']*distance[x+y:].sum())

    def components(self, chosen, details=False):
        connection=sum(q*self.role_distance((ma,ra),(mb,rb),chosen)
                       for (ma,ra,mb,rb),q in self.edges.items())
        square=0.;boundaries=0.;over_one=0.;all_hist=Counter();per_pattern=[]
        for roles,q in self.paths.items():
            key=tuple((tuple(chosen[m]['bounds']),r,a) for m,r,a in roles)
            if key not in self.path_cache:
                probabilities=[self.profile(chosen[m],r)[1] for m,r,a in roles]
                hist=crossing_distribution(probabilities,[a for m,r,a in roles])
                self.path_cache[key]=(positive_square(hist),sum(n*p for n,p in hist.items()),hist)
            penalty,n,hist=self.path_cache[key]
            square+=q*penalty;count=self.path_counts[roles]
            boundaries+=count*n;over_one+=count*sum(p for n,p in hist.items() if n>1)
            for n,p in hist.items():all_hist[n]+=count*p
            if details:per_pattern.append(dict(roles=roles,weight=q,count=count,distribution=hist))
        result=dict(critical_connection_distance=connection,weighted_path_square=square,
                    path_expected_boundaries=boundaries,path_expected_over_one=over_one,
                    critical_connection_term=self.cfg['critical_distance_weight']*connection,
                    path_square_term=self.cfg['path_square_weight']*square)
        if details:result.update(path_boundary_histogram=dict(all_hist),path_patterns=per_pattern)
        return result

    def broadcast(self, chosen):
        f=self.feedback['broadcast'];source=self.feedback['nodes'][str(f['source'])]
        _,p=self.profile(chosen[source['module']],source['resource'])
        count=0.;hist=Counter();modules=Counter()
        for a in f['sinks']:
            node=self.feedback['nodes'][str(a)];modules[node['module']]+=1
            if a==f['source']:
                hist[0]+=1;continue
            _,q=self.profile(chosen[node['module']],node['resource'])
            for i,j in itertools.product(range(len(p)),repeat=2):hist[abs(i-j)]+=p[i]*q[j]
        return dict(source_module=source['module'],sink_pins=len(f['sinks']),sink_modules=dict(modules),
                    expected_boundary_histogram=dict(hist),expected_far_sink_pins=sum(v for d,v in hist.items() if d>=2),
                    maximum_supported_branch_span=max(d for d,v in hist.items() if v>1e-10))
