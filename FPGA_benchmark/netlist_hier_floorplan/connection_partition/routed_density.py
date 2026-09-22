"""Small routed-density fit for coarse CR allocation; no placement prediction."""
import hashlib
import json

def coordinates(cr, region, device):
    x0, y0, x1, y1 = region['bounds']
    return (2*(device[cr]['x']-x0+.5)/(x1-x0+1)-1,
            2*(device[cr]['y']-y0+.5)/(y1-y0+1)-1)


def fit_profile(counts, reference, device, strength=.5):
    """Fit a bilinear utilization surface per resource inside the old core.

    counts is {resource: {cr: observed_slots}}. Relative coordinates let the
    trend move/stretch with a candidate region. Out-of-core cells inform the
    recorded coverage only; they are not projected into a different module.
    """
    import numpy as np
    if not 0 <= strength <= 1:
        raise ValueError('strength must be between zero and one')
    fitted = {}
    for resource, observed in counts.items():
        crs = [c for c in reference['crs'] if device[c]['resources'][resource]]
        inside = sum(observed.get(c, 0) for c in crs)
        if not crs or not inside:
            continue
        xy = [coordinates(c, reference, device) for c in crs]
        axes = [0]
        if len({x for x, y in xy}) > 1: axes.append(1)
        if len({y for x, y in xy}) > 1: axes.append(2)
        if 1 in axes and 2 in axes: axes.append(3)
        a = np.array([[1, x, y, x*y] for x, y in xy])
        u = np.array([observed.get(c, 0)/device[c]['resources'][resource] for c in crs])
        coef = np.zeros(4)
        coef[axes] = np.linalg.lstsq(a[:, axes], u, rcond=None)[0]
        fitted[resource] = dict(coefficients=coef.tolist(), observed_in_core=inside,
                                observed_total=sum(observed.values()))
    result = dict(schema='bilinear-routed-density-v1', strength=strength,
                  reference_bounds=reference['bounds'], resources=fitted)
    result['id'] = hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()
    return result


def resource_probabilities(region, device, resource):
    """Mix fitted density and the capacity prior; sum to one when sites exist.

    Resource demand is unchanged. Zero-capacity CRs always receive zero demand.
    A missing/empty profile falls back to the original capacity distribution.
    """
    capacity = {c: device[c]['resources'][resource] for c in region['crs']}
    total = sum(capacity.values())
    if not total: return dict.fromkeys(capacity, 0.)
    prior = {c: v/total for c, v in capacity.items()}
    profile = region.get('density_profile', {})
    data = profile.get('resources', {}).get(resource)
    alpha = profile.get('strength', 0.)
    if not data or not alpha: return prior
    if not 0 <= alpha <= 1: raise ValueError('Invalid density strength')
    a, b, d, e = data['coefficients']
    weighted = {}
    for c, cap in capacity.items():
        x, y = coordinates(c, region, device)
        weighted[c] = cap*max(0., a+b*x+d*y+e*x*y)
    mass = sum(weighted.values())
    if mass <= 1e-15: return prior
    return {c: (1-alpha)*prior[c]+alpha*weighted[c]/mass for c in capacity}


def region_cache_key(region):
    # Include all profile values: identical geometry can belong to different modules.
    return (tuple(sorted(region['crs'])),
            json.dumps(region.get('density_profile'), sort_keys=True, separators=(',', ':')))
