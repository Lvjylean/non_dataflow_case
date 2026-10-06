"""Compare real native static-cache probe evidence; never launches Vivado."""
import argparse
import csv
import importlib.util
import json
from pathlib import Path


def module(code):
    spec = importlib.util.spec_from_file_location('bl_static_cache', code/'code/regional/static_discovery_cache.py')
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value)
    return value


def inventory_metadata(path):
    with path.open() as stream:
        data = {row['key']: row['value'] for row in csv.DictReader(stream, delimiter='\t')}
    # These values report where/how long the unchanged inventory was captured.
    # No logical, eligibility, resource or coverage field may be normalized.
    for field in ('elapsed_ms', 'cells_path', 'edges_path', 'diagnostics_path'):
        data.pop(field, None)
    return data


def compare(code, out):
    cache = module(code)
    for stage in ('live', 'fresh', 'cached'):
        if not (out/stage/'NATIVE_COMPLETE').is_file():
            raise ValueError('Missing native completion: '+stage)
    live, fresh, cached = (out/stage/'locality' for stage in ('live', 'fresh', 'cached'))
    evidence = []
    for name in cache.FILES:
        paths = [folder/name for folder in (live, fresh, cached)]
        if name == 'metadata.tsv':
            values = [inventory_metadata(p) for p in paths]
        elif name == 'proposals.json':
            values = [json.loads(p.read_text()) for p in paths]
        else:
            values = [p.read_bytes() for p in paths]
        if values[0] != values[1] or values[1] != values[2]:
            raise ValueError('Native static evidence differs: '+name)
        evidence.append(dict(name=name, sha256={s:cache.sha(p) for s,p in zip(('live','fresh','cached'),paths)}))
    receipt = json.loads((cached/'static_cache_restore.json').read_text())
    if receipt.get('status') != 'HIT':
        raise ValueError('Native cached stage did not reuse the cache')
    if not json.loads((out/'exclude.json').read_text()):
        raise ValueError('The exclusion case must be nonempty')
    for relative in ('joint_candidates.json', 'locality/final_plan.tcl'):
        a, b = out/'fresh'/relative, out/'cached'/relative
        av = json.loads(a.read_text()) if a.suffix == '.json' else a.read_bytes()
        bv = json.loads(b.read_text()) if b.suffix == '.json' else b.read_bytes()
        if av != bv:
            raise ValueError('Native fresh/cached retry admission differs: '+relative)
        evidence.append(dict(name=relative, fresh_sha256=cache.sha(a), cached_sha256=cache.sha(b)))
    hashes = cache.code_inventory(code)
    if json.loads((out/'source_manifest.json').read_text()) != hashes:
        raise ValueError('Probe source changed after execution')
    result = dict(status='PASS', source_hashes=hashes,
                  live_vs_reopened_static_equivalent=True, retry_finish_equivalent=True,
                  checkpoint_sha256=cache.sha(out/'base/pre_route.dcp'), evidence=evidence,
                  excluded=json.loads((out/'exclude.json').read_text()),
                  scope='static discovery only; all native timing and finish admission rerun')
    cache.write(out/'native_static_discovery_cache_evidence.json', result)
    return result


def main():
    ap=argparse.ArgumentParser();ap.add_argument('mode',choices=('manifest','exclude','compare'))
    ap.add_argument('code',type=Path);ap.add_argument('out',type=Path);args=ap.parse_args()
    cache=module(args.code)
    if args.mode == 'manifest':
        cache.write(args.out/'source_manifest.json',cache.code_inventory(args.code))
    elif args.mode == 'exclude':
        choices=json.loads((args.out/'live/joint_candidates.json').read_text())['keep']
        if not choices:raise ValueError('Fixture has no selected candidate to exclude')
        cache.write(args.out/'exclude.json',[choices[0]])
    else:print(json.dumps(compare(args.code,args.out)))


if __name__=='__main__':main()
