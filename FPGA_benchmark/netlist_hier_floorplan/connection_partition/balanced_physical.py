"""All-atom hypernet span estimates; internal nets never become free by relabeling."""
from collections import Counter

import numpy as np

from static_regions import RESOURCES
from routed_density import resource_probabilities, region_cache_key

# A fixed atom classification, independent of the candidate partition.
PRIORITY = ('URAM','BRAM18','DSP','CARRY8','MUXF8','MUXF7','LUTMEM','LUT','FF')


def atom_resource(demand):
    return next(r for r in PRIORITY if demand.get(r, 0))


def cdf_table(region, device):
    """Coarse location distribution, optionally fitted to routed resource density."""
    thresholds = [(key,t) for key in ('x','y','slr')
                  for t in range(max(d[key] for d in device.values()))]
    result = np.zeros((len(RESOURCES), len(thresholds)))
    for ri,r in enumerate(RESOURCES):
        probabilities = resource_probabilities(region, device, r)
        for ti,(key,t) in enumerate(thresholds):
            result[ri,ti] = sum(probabilities[c] for c in region['crs']
                                if device[c][key] <= t)
    return result


def expected_ranges(counts, cdf):
    """E[max-min] for independent locations; supports repeated distributions."""
    left = counts @ np.log(np.clip(cdf, 1e-300, 1.0))
    right = counts @ np.log(np.clip(1-cdf, 1e-300, 1.0))
    return np.maximum(0, 1-np.exp(left)-np.exp(right))


class NetModel:
    def __init__(self, data, labels, module_count, device):
        self.device=device
        self.modules=module_count
        self.dimensions=[max(d[key] for d in device.values()) for key in ('x','y','slr')]
        resources=[RESOURCES.index(atom_resource(r)) for r in data['atom_resources']]
        patterns=Counter()
        for edge,weight in data['edges']:
            p=tuple(sorted(Counter(labels[a]*len(RESOURCES)+resources[a] for a in edge).items()))
            patterns[p]+=weight/4
        self.patterns=list(patterns)
        self.weights=np.array(list(patterns.values()), dtype=float)
        self.counts=np.zeros((len(patterns), module_count*len(RESOURCES)))
        self.pattern_modules=[]
        for i,p in enumerate(patterns):
            for slot,n in p:
                self.counts[i,slot]=n
            self.pattern_modules.append({slot//len(RESOURCES) for slot,_ in p})
        self.internal={m:np.array([i for i,ms in enumerate(self.pattern_modules) if ms=={m}],dtype=int)
                       for m in range(module_count)}
        self.cross=np.array([len(ms)>1 for ms in self.pattern_modules])
        self._cache={}
        assert abs(self.weights.sum()-sum(w for _,w in data['edges'])/4)<1e-6

    def cdf(self, region):
        key=region_cache_key(region)
        if key not in self._cache:
            self._cache[key]=cdf_table(region,self.device)
        return self._cache[key]

    def components(self, chosen, slr_weight=4):
        table=np.vstack([self.cdf(chosen[f'P{m:02d}']) for m in range(self.modules)])
        ranges=expected_ranges(self.counts,table)
        spans=self.weights @ ranges
        n0,n1,n2=self.dimensions
        costs=dict(x_span=float(spans[:n0].sum()),y_span=float(spans[n0:n0+n1].sum()),
                   slr_span=float(spans[n0+n1:].sum()))
        factors=np.array([1]*n0+[1]*n1+[slr_weight]*n2)
        pernet=ranges @ factors
        costs['internal_span_cost']=float(self.weights[~self.cross] @ pernet[~self.cross])
        costs['boundary_span_cost']=float(self.weights[self.cross] @ pernet[self.cross])
        costs['physical_cost']=costs['x_span']+costs['y_span']+slr_weight*costs['slr_span']
        return costs

    def internal_region_cost(self, m, region, slr_weight=4):
        ids=self.internal[m]
        if not len(ids):
            return 0.0
        lo=m*len(RESOURCES);hi=lo+len(RESOURCES)
        ranges=expected_ranges(self.counts[ids,lo:hi], self.cdf(region))
        n0,n1,n2=self.dimensions
        factors=np.array([1]*(n0+n1)+[slr_weight]*n2)
        return float(self.weights[ids] @ (ranges @ factors))


def balanced_score(components, metrics, all_net_weight, cfg):
    physical=components['x_span']+components['y_span']+cfg['slr_distance_weight']*components['slr_span']
    return (physical+cfg['cut_weight']*metrics['weighted_km1']
            +cfg['logical_core_weight']*metrics['logical_core_loss']
            +cfg['module_cost_fraction_of_all_net_weight']*all_net_weight*metrics['module_count'])


def admissible(metrics, cfg, multiplier=1):
    return (metrics['global_added_fraction'] <= multiplier*cfg['global_added_km1_fraction_of_all_net_weight']+1e-12
            and metrics['maximum_local_split_fraction'] <= multiplier*cfg['local_split_fraction_of_incident_net_weight']+1e-12)
