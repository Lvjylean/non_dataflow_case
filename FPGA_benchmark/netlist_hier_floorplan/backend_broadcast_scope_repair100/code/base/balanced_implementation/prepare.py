"""Validate and adapt frozen balanced exports without repartitioning."""
import argparse
import csv
import gzip
import hashlib
import json
import shutil
from collections import Counter
from pathlib import Path

RESOURCES = ('LUT', 'FF', 'DSP', 'BRAM18', 'URAM', 'CARRY8', 'MUXF7', 'MUXF8', 'LUTMEM')


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def prepare(source, output, count):
    source, output = Path(source).resolve(), Path(output).resolve()
    modules = json.loads((source / 'modules.json').read_text())
    plan = json.loads((source / 'static_regions.json').read_text())
    rows = {m['module_id']: m for m in modules['modules']}
    assert len(rows) == count and set(rows) == set(plan['regions'])
    assert plan['status'] == 'feasible'
    assert digest(modules['input_dcp']) == modules['input_sha256']
    for mid, region in plan['regions'].items():
        x0, y0, x1, y1 = region['bounds']
        expected = {f'X{x}Y{y}' for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)}
        assert expected == set(region['crs']) and len(expected) == len(region['crs'])
        assert rows[mid]['incoming_pin_connections'] + rows[mid]['outgoing_pin_connections'] > 0
    output.mkdir(parents=True, exist_ok=False)
    frozen = output / 'export'
    shutil.copytree(source, frozen)
    counts = Counter()
    totals = Counter()
    per_module = {mid: Counter() for mid in rows}
    names = set()
    with gzip.open(frozen / 'leaf_cells.tsv.gz', 'rt') as f, (output / 'membership.tsv').open('w') as out:
        writer = csv.writer(out, delimiter='\t', lineterminator='\n')
        writer.writerow(['cell', 'module', 'resource', 'ref'])
        for index, row in enumerate(csv.DictReader(f, delimiter='\t')):
            name, mid, ref = row['cell_name'], row['module_id'], row['primitive']
            assert row['cell_id'] == f'c{index}' and name not in names
            assert not any(c in name for c in '\n\r\t')
            names.add(name)
            counts[mid] += 1
            resources = {r: int(row[r]) for r in RESOURCES}
            totals.update(resources)
            if mid in rows:
                per_module[mid].update(resources)
            else:
                assert mid in modules['infrastructure']
            resource = next((r for r in ('DSP', 'URAM', 'BRAM18', 'FF', 'LUT', 'CARRY8', 'MUXF8', 'MUXF7') if resources[r]), 'OTHER')
            writer.writerow([name, mid, resource, ref])
    assert len(names) == modules['validation']['all_cells']
    for mid, row in rows.items():
        assert counts[mid] == row['cells']
        assert all(per_module[mid][r] == row[r] for r in RESOURCES)
    assert all(totals[r] == modules['total_resources'][r] for r in RESOURCES)
    assert all(counts[mid] == n for mid, n in modules['infrastructure'].items())
    tcl = ['set planned_regions [dict create]', 'set planned_bounds [dict create]']
    for mid, region in sorted(plan['regions'].items()):
        assert mid.isalnum()
        tcl.append(f'dict set planned_regions {mid} {{{" ".join(region["crs"])}}}')
        tcl.append(f'dict set planned_bounds {mid} {{{" ".join(map(str, region["bounds"]))}}}')
    (output / 'regions.tcl').write_text('\n'.join(tcl) + '\n')
    manifest = dict(source=str(source), input_dcp=modules['input_dcp'], input_sha256=modules['input_sha256'],
                    module_count=count, original_cells=len(names), counts=dict(counts), resource_totals=dict(totals),
                    files={str(p.relative_to(output)): digest(p) for p in sorted(output.rglob('*')) if p.is_file()},
                    scope='Exact frozen memberships and CR rectangles; no new partition or ILP.')
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    return manifest


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('source', type=Path)
    p.add_argument('output', type=Path)
    p.add_argument('count', type=int)
    a = p.parse_args()
    print(json.dumps(prepare(a.source, a.output, a.count)), flush=True)
