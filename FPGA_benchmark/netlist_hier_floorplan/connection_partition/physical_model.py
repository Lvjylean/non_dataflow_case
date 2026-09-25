"""Explicit version selection for legacy and boundary-based spatial costs."""
from balanced_physical import NetModel

LEGACY = 'all_atom_v1'


def build(data, labels, module_count, device, cfg):
    name = cfg.get('hypernet_model', LEGACY)
    if name == LEGACY:
        return NetModel(data, labels, module_count, device)
    if name == 'boundary_spatial_v1':
        from boundary_hyper import BoundaryNetModel
        return BoundaryNetModel(data, labels, module_count, device,
                                cfg.get('boundary_frontier_max_entries', 10000000))
    raise ValueError('Unknown hypernet model: ' + str(name))


def check_cache(model, cfg):
    actual = getattr(model, 'schema', LEGACY)
    expected = cfg.get('hypernet_model', LEGACY)
    if actual != expected:
        raise ValueError(f'Hypernet cache is {actual}, configuration requests {expected}; '
                         'rebuild from the original graph and frozen module membership.')
