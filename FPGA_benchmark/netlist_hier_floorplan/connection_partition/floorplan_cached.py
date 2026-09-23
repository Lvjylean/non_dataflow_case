"""Re-run a fixed-membership floorplan from trusted, bound local caches."""
import argparse
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys


SOURCE = Path(__file__).resolve().parent


def load(path):
    return json.loads(path.read_text())


def dump(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def prepare(run, previous, references):
    from static_regions import LIMITS
    from edge_padding import POLICY
    cfg = load(SOURCE / 'directed_config.json')
    if cfg['resource_limits'] != LIMITS:
        raise ValueError('Resource config and static_regions.LIMITS disagree.')
    if cfg['soft_expansion_threshold'] != POLICY['threshold']:
        raise ValueError('Soft expansion config and edge_padding.POLICY disagree.')
    if cfg.get('routed_density_profile'):
        raise ValueError('This release uses capacity-proportional resources, without routed fitting.')
    required = ['input/export/modules.json', 'input/export/static_regions.json',
                'input/original_regions.json', 'input/cr.tsv', 'netmodel.pkl',
                'directed.json', 'binding.json']
    for name in required:
        if not (previous / name).is_file():
            raise FileNotFoundError(previous / name)
    modules = load(previous / 'input/export/modules.json')['modules']
    if not modules or [m['module_id'] for m in modules] != [
            f'S{i:02d}' for i in range(len(modules))]:
        raise ValueError('Cached search requires ordered S00... module IDs.')
    binding = load(previous / 'binding.json')
    immutable = binding.get('immutable_files')
    if immutable is None:
        local = load(previous / 'local_binding.json')
        immutable = local['source_sha256']
    expected = {v for k, v in immutable.items() if k.endswith('netmodel.pkl')}
    if not expected:
        raise ValueError('No bound net-model hash is available.')
    if sha(previous / 'netmodel.pkl') not in expected:
        raise ValueError('Net-model cache does not match its input binding.')
    parsed = []
    for entry in references:
        name, separator, path = entry.partition('=')
        if not separator or not re.fullmatch(r'[A-Za-z0-9_-]+', name):
            raise ValueError('Each --reference must be NAME=JSON_PATH.')
        plan = Path(path).resolve()
        if set(load(plan)['regions']) != {m['module_id'] for m in modules}:
            raise ValueError('Reference module labels differ: ' + str(plan))
        parsed.append((name, plan))
    if len({n for n, _ in parsed}) != len(parsed):
        raise ValueError('Reference names must be unique.')
    run.mkdir(parents=True, exist_ok=False)
    shutil.copytree(SOURCE, run / 'source', ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copy2(SOURCE.parent / 'balanced_implementation/adapter.tcl',
                 run / 'source/adapter_reference.tcl')
    shutil.copytree(previous / 'input', run / 'input')
    for name in ['netmodel.pkl', 'directed.json', 'binding.json']:
        shutil.copy2(previous / name, run / name)
    if not parsed:
        refs = [dict(name='w8', path='input/export/static_regions.json'),
                dict(name='early', path='input/original_regions.json')]
    else:
        folder = run / 'input/search_references'
        folder.mkdir(exist_ok=True)
        refs = []
        for i, (name, path) in enumerate(parsed):
            target = folder / f'{i}_{name}.json'
            shutil.copy2(path, target)
            refs.append(dict(name=name, path=str(target.relative_to(run))))
    dump(run / 'search_references.json', refs)
    dump(run / 'source/manifest.json', {
        p.name: sha(p) for p in (run / 'source').iterdir()
        if p.is_file() and p.name != 'manifest.json'})
    files = [p for p in (run / 'input').rglob('*') if p.is_file()]
    files += [run / n for n in ['netmodel.pkl', 'directed.json', 'search_references.json']]
    dump(run / 'local_binding.json', dict(
        reference=str(previous), original_dcp=binding['input_dcp'],
        original_dcp_sha256=binding['input_sha256'],
        source_sha256={str(p.relative_to(run)): sha(p) for p in files},
        remote_accessed=False, scope='Local static floorplan; unchanged memberships.'))


def export(run):
    from edge_padding_export import build_envelope
    from edge_padding import regions_tcl, geometry_adapter
    from edge_padding_plot_local import plots
    from static_regions import RESOURCES, load_device
    core = load(run / 'solution.json')
    modules = load(run / 'export/modules.json')['modules']
    device = load_device(run / 'input/cr.tsv')
    soft, changes = build_envelope(modules, core, device, '../solution.json')
    # Independently enumerate each empty target CR, using exact rational pressure.
    cores = {m: set(r['crs']) for m, r in core['regions'].items()}
    occupied = set().union(*cores.values())
    expected = {m: set(c) for m, c in cores.items()}
    threshold = Fraction(str(core['configuration']['soft_expansion_threshold']))
    for target, d in device.items():
        if target in occupied:
            continue
        for mid, crs in cores.items():
            for c in crs:
                loc = device[c]
                if loc['slr'] != d['slr'] or abs(loc['x']-d['x']) + abs(loc['y']-d['y']) != 1:
                    continue
                pressure = {r: sum((Fraction(m[r], core['regions'][m['module_id']]['capacity'][r])
                            for m in modules if c in cores[m['module_id']] and m[r] and loc['resources'][r]),
                            Fraction(0)) for r in RESOURCES}
                if max(pressure.values()) > threshold:
                    expected[mid].add(target)
    assert expected == {m: set(r['crs']) for m, r in soft['regions'].items()}
    assert soft['planning_regions'] == core['regions']
    assert all(soft[k] == core[k] for k in ['components', 'objective', 'overlap'])
    assert all('capacity' not in r for r in soft['regions'].values())
    folder = run / 'soft'
    (folder / 'input/export').mkdir(parents=True)
    shutil.copy2(run / 'solution.json', folder / 'input/export/static_regions.json')
    shutil.copy2(run / 'solution.json', folder / 'core_solution.json')
    shutil.copy2(run / 'input/cr.tsv', folder / 'input/cr.tsv')
    dump(folder / 'solution.json', soft)
    dump(folder / 'edge_padding.json', changes)
    (folder / 'regions.tcl').write_text(regions_tcl(soft['regions']))
    (folder / 'soft_region_adapter.tcl').write_text(
        geometry_adapter(run / 'source/adapter_reference.tcl'))
    plots(folder)
    dump(run / 'delivery_verification.json', dict(
        status='PASS', exact_target_centric_expansion=True,
        core_cost_and_resources_unchanged=True, placement_and_route=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path, help='New output directory; must not exist.')
    parser.add_argument('--from-run', required=True, type=Path, help='Existing trusted directed floorplan cache run.')
    parser.add_argument('--reference', action='append', default=[], metavar='NAME=JSON',
                        help='Optional ordered starting plans; replaces the two default references.')
    args = parser.parse_args()
    run = args.output.resolve()
    prepare(run, args.from_run.resolve(), args.reference)
    for stage in ['fixed11_search', 'fixed11_explore', 'fixed11_verify']:
        with (run / (stage + '.log')).open('w') as log:
            subprocess.run([sys.executable, str(run / 'source' / (stage + '.py')), str(run)],
                           stdout=log, stderr=subprocess.STDOUT, check=True)
        print(stage + ': PASS', flush=True)
    export(run)
    print(json.dumps(dict(status='PASS', run=str(run), objective=load(run / 'solution.json')['objective'])), flush=True)


if __name__ == '__main__':
    main()
