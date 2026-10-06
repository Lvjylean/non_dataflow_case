"""Boundary-based directed spatial distance; raw branch risk stays separate."""
from collections import Counter
import math

import numpy as np

from boundary_hyper import TYPES
from static_regions import RESOURCES
from routed_density import resource_probabilities, region_cache_key

SCHEMA = 'boundary_directed_v1'
LEGACY = 'raw_sink_pin_v1'


def selection(cfg):
    name = cfg.get('directed_distance_model', LEGACY)
    if name not in (SCHEMA, LEGACY):
        raise ValueError('Unknown directed distance model: ' + str(name))
    return name


def attach(raw, model, cfg):
    """Never reinterpret the raw nine-resource slots as lifted ten-role slots."""
    if selection(cfg) == LEGACY:
        return raw
    if not hasattr(model, 'directed_data'):
        raise ValueError('Directed boundary distance requires rebuilding from the original graph and frozen membership.')
    return dict(raw, spatial=model.directed_data)


def profiles(region, device):
    result = []
    for resource in RESOURCES:
        probabilities = resource_probabilities(region, device, resource)
        result.append([(tuple(device[c][axis] for axis in ('x', 'y', 'slr')), p)
                       for c,p in probabilities.items() if p])
    lut = result[RESOURCES.index('LUT')]
    center = tuple(sum(point[axis]*p for point,p in lut) for axis in range(3))
    result.append([(center, 1.)] if lut else [])
    return result


class BoundaryDirectedModel:
    def __init__(self, data, device, cfg, module_ids):
        if data.get('schema') != SCHEMA or data.get('resource_types') != list(TYPES):
            raise ValueError('Missing/stale directed boundary cache; rebuild from the original graph and frozen membership.')
        if data['module_count'] != len(module_ids):
            raise ValueError('Directed boundary module count mismatch.')
        self.data, self.device, self.cfg, self.ids = data, device, cfg, module_ids
        n = len(module_ids)*len(TYPES)
        self.weights = np.zeros((n,n))
        for edge in data['pairs']:
            a,b,w = edge['source'],edge['sink'],edge['weight']
            if not (type(a) is int and type(b) is int and 0<=a<n and 0<=b<n
                    and math.isfinite(w) and w>=0):
                raise ValueError('Invalid directed boundary pair.')
            self.weights[a,b] += w
        self.cache = {}
        modules = np.arange(n)//len(TYPES)
        self.internal = modules[:,None] == modules[None,:]

    def profile(self, region):
        key = region_cache_key(region)
        if key not in self.cache:
            self.cache[key] = profiles(region, self.device)
        return self.cache[key]

    @staticmethod
    def distances(distributions, axis):
        coordinates = sorted({point[axis] for profile in distributions for point,p in profile if p})
        n = len(distributions)
        if len(coordinates)<2:
            return np.zeros((n,n))
        cuts = np.asarray(coordinates[:-1])
        widths = np.diff(coordinates)
        cdf = np.zeros((n,len(cuts)))
        for i,profile in enumerate(distributions):
            for point,p in profile:
                cdf[i] += p*(point[axis]<=cuts)
        sums = cdf@widths
        return np.maximum(0, sums[:,None]+sums[None,:]-2*(cdf*widths)@cdf.T)

    def _cost(self, distributions, weights, internal):
        active = np.any(weights>0,axis=0)|np.any(weights>0,axis=1)
        if any(not distributions[i] for i in np.flatnonzero(active)):
            raise ValueError('Retained directed anchor/proxy lacks resource capacity.')
        axes = [self.distances(distributions,axis) for axis in range(3)]
        value = axes[0]+axes[1]+self.cfg['slr_distance_weight']*axes[2]
        result = {name:float(np.sum(weights*distance)) for name,distance in
                  zip(('directed_x','directed_y','directed_slr'),axes)}
        result.update(directed_distance=float(np.sum(weights*value)),
                      directed_internal_distance=float(np.sum(weights*value*internal)))
        result['directed_term'] = self.cfg['directed_weight']*result['directed_distance']
        return result

    def components(self, chosen):
        return self._cost([p for mid in self.ids for p in self.profile(chosen[mid])],
                          self.weights,self.internal)

    def internal_cost(self, module, region):
        n = len(TYPES); lo,hi = module*n,(module+1)*n
        return self._cost(self.profile(region),self.weights[lo:hi,lo:hi],
                          np.ones((n,n),dtype=bool))['directed_term']


def independent_components(data, chosen, device, cfg, module_ids):
    """Explicit support-pair enumeration, independent of matrix/CDF scoring."""
    role_profiles = []
    for mid in module_ids:
        region = chosen[mid]; values = []
        for resource in RESOURCES:
            if region.get('density_profile'):
                raise ValueError('Independent boundary verifier requires unfitted resource profiles.')
            caps = {c:device[c]['resources'][resource] for c in region['crs']}
            total = sum(caps.values())
            values.append([(tuple(device[c][a] for a in ('x','y','slr')),cap/total)
                           for c,cap in caps.items() if cap])
        lut = values[RESOURCES.index('LUT')]
        values.append([(tuple(sum(point[a]*p for point,p in lut) for a in range(3)),1.)] if lut else [])
        role_profiles.extend(values)
    sums = Counter(); memo = {}
    for edge in data['pairs']:
        a,b,w = edge['source'],edge['sink'],edge['weight']
        if not role_profiles[a] or not role_profiles[b]:
            raise ValueError('Retained directed anchor/proxy lacks resource capacity.')
        if (a,b) not in memo:
            memo[a,b] = [sum(pa*pb*abs(x[axis]-y[axis]) for x,pa in role_profiles[a]
                            for y,pb in role_profiles[b]) for axis in range(3)]
        x,y,s = memo[a,b]
        sums['directed_x'] += w*x; sums['directed_y'] += w*y; sums['directed_slr'] += w*s
        if a//len(TYPES)==b//len(TYPES):
            sums['directed_internal_distance'] += w*(x+y+cfg['slr_distance_weight']*s)
    for key in ('directed_x','directed_y','directed_slr','directed_internal_distance'):
        sums[key] += 0.
    sums['directed_distance'] = sums['directed_x']+sums['directed_y']+cfg['slr_distance_weight']*sums['directed_slr']
    sums['directed_term'] = cfg['directed_weight']*sums['directed_distance']
    return dict(sums)
