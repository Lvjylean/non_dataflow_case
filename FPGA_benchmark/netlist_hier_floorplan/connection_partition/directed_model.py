"""All original directed sink-pin branches, aggregated without losing multiplicity."""
import numpy as np
from balanced_physical import cdf_table
from static_regions import RESOURCES
from routed_density import region_cache_key


class DirectedModel:
    def __init__(self, data, device, cfg):
        self.data, self.device, self.cfg = data, device, cfg
        self.count = data['module_count'] * len(RESOURCES)
        self.dimensions = [max(d[key] for d in device.values()) for key in ('x','y','slr')]
        self.weights = np.zeros((self.count, self.count))
        self.counts = np.zeros_like(self.weights)
        for pair in data['pairs']:
            a,b = pair['source'],pair['sink']
            self.weights[a,b] += pair['weight']
            self.counts[a,b] += pair['pins']
        self.cache = {}
        indices = np.arange(self.count)//len(RESOURCES)
        self.internal_mask = indices[:,None] == indices[None,:]

    def profile(self, region):
        key = region_cache_key(region)
        if key not in self.cache:
            f = cdf_table(region,self.device)
            x,y,_ = self.dimensions
            p = np.clip(np.diff(np.c_[np.zeros(len(RESOURCES)),f[:,x+y:],np.ones(len(RESOURCES))],axis=1),0,1)
            self.cache[key] = f,p
        return self.cache[key]

    def distances(self, table, probabilities):
        x,y,z = self.dimensions
        def l1(f):
            sums = f.sum(axis=1)
            return np.maximum(0,sums[:,None]+sums[None,:]-2*f@f.T)
        dx,dy = l1(table[:,:x]),l1(table[:,x:x+y])
        separation = abs(np.arange(z+1)[:,None]-np.arange(z+1)[None,:])
        ds = probabilities@separation@probabilities.T
        square = probabilities@np.maximum(0,separation-1)**2@probabilities.T
        far = probabilities@(separation>1)@probabilities.T
        return dx,dy,ds,square,far,separation

    def components(self, chosen, details=False):
        profiles = [self.profile(chosen[f'S{i:02d}']) for i in range(self.data['module_count'])]
        table = np.vstack([p[0] for p in profiles]);prob = np.vstack([p[1] for p in profiles])
        dx,dy,ds,square,far,separation = self.distances(table,prob)
        weighted = lambda m: float(np.sum(self.weights*m))
        direct = weighted(dx+dy+self.cfg['slr_distance_weight']*ds)
        result = dict(directed_x=weighted(dx),directed_y=weighted(dy),directed_slr=weighted(ds),
            directed_distance=direct,branch_square=weighted(square),weighted_far_pins=weighted(far),
            raw_far_pins=float(np.sum(self.counts*far)),raw_branch_boundaries=float(np.sum(self.counts*ds)),
            directed_internal_distance=float(np.sum(self.weights*self.internal_mask*(dx+dy+self.cfg['slr_distance_weight']*ds))))
        result['directed_term'] = self.cfg['directed_weight']*direct
        result['branch_square_term'] = self.cfg['branch_square_weight']*result['branch_square']
        if details:
            result['raw_boundary_histogram'] = {str(d):float(np.sum(self.counts*(prob@(separation==d)@prob.T))) for d in range(self.dimensions[2]+1)}
            result['raw_boundary_histogram']['0'] += self.data['coverage']['same_atom_pins']
        return result

    def internal_cost(self, module, region):
        n=len(RESOURCES);lo=module*n;hi=lo+n
        f,p=self.profile(region);dx,dy,ds,square,_,_=self.distances(f,p)
        value=self.cfg['directed_weight']*(dx+dy+self.cfg['slr_distance_weight']*ds)+self.cfg['branch_square_weight']*square
        return float(np.sum(self.weights[lo:hi,lo:hi]*value))

    def family_audit(self, chosen):
        profiles=[self.profile(chosen[f'S{i:02d}'])[1] for i in range(self.data['module_count'])]
        p=np.vstack(profiles);z=self.dimensions[2]
        sep=abs(np.arange(z+1)[:,None]-np.arange(z+1)[None,:])
        output={}
        for name, family in self.data['families'].items():
            hist=np.zeros(z+1)
            for e in family['pairs']:
                joint=p[e['source']][:,None]*p[e['sink']][None,:]
                for d in range(z+1):hist[d]+=e['pins']*np.sum(joint*(sep==d))
            hist[0]+=family['same_atom_pins']
            output[name]=dict(nets=family['nets'],sink_pins=family['sink_pins'],
                expected_boundary_histogram={str(d):float(v) for d,v in enumerate(hist)},
                far_sink_pins=float(hist[2:].sum()),maximum_supported_span=max(d for d,v in enumerate(hist) if v>1e-8))
        return output
