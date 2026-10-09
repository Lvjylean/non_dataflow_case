"""Compare real native static-cache probe evidence; never launches Vivado."""
import argparse
import csv
import importlib.util
import json
from pathlib import Path

PROOF_SCHEMA = 'native-static-discovery-equivalence-v2'
FRESH_NATIVE_TABLES = (
    'ji_candidates.tsv', 'ji_cones.tsv', 'ji_cells.tsv', 'ji_edges.tsv',
    'ji_nets.tsv', 'ji_slacks.tsv', 'ji_capacity.tsv',
    'locality/template_status.tsv', 'locality/through_slacks.tsv',
)


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


def table(path):
    """Ignore native enumeration order only; preserve duplicate rows and all values."""
    with path.open(newline='') as stream:
        rows = list(csv.reader(stream, delimiter='\t'))
    if not rows:
        raise ValueError('Empty native table: '+str(path))
    if any(len(row) != len(rows[0]) for row in rows[1:]):
        raise ValueError('Malformed native table: '+str(path))
    return rows[0], sorted(rows[1:])


def compare(code, out):
    cache = module(code)
    for stage in ('live', 'fresh', 'cached'):
        if not (out/stage/'NATIVE_COMPLETE').is_file():
            raise ValueError('Missing native completion: '+stage)
    live, fresh, cached = (out/stage/'locality' for stage in ('live', 'fresh', 'cached'))
    contexts = [json.loads((folder/'static_context.json').read_text()) for folder in (live, fresh, cached)]
    if len({json.dumps(cache.key(context), sort_keys=True) for context in contexts}) != 1:
        raise ValueError('Native stage cache identities differ')
    if [context['producer_state'] for context in contexts] != ['live_base', 'reopened_base', 'reopened_base']:
        raise ValueError('Native probe producer states differ')
    for context in contexts:
        cache.revalidate(context)
    runtimes = {}
    for stage, context in zip(('live', 'fresh', 'cached'), contexts):
        header, rows = table(out/stage/'native_context.tsv')
        if header != ['key', 'value'] or len({row[0] for row in rows}) != len(rows):
            raise ValueError('Malformed native context: '+stage)
        native = dict(rows)
        for name in ('vivado_version', 'part', 'checkpoint'):
            observed = native.get(name)
            if name == 'checkpoint' and observed:
                observed = str(Path(observed).resolve())
            if observed != context[name]:
                raise ValueError('Native context mismatch: '+stage+':'+name)
        if native.get('mode') != stage:
            raise ValueError('Native mode mismatch: '+stage)
        runtimes[stage] = int(native['discovery_ms'])/1000
        if runtimes[stage] < 0:
            raise ValueError('Negative native discovery time: '+stage)
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
    if receipt.get('context') != contexts[2] or receipt.get('files') != cache.validate_outputs(live):
        raise ValueError('Native cache restore receipt identity differs')
    excluded = json.loads((out/'exclude.json').read_text())
    if not isinstance(excluded, list) or not excluded or any(not isinstance(value, str) for value in excluded):
        raise ValueError('The exclusion case must be nonempty')
    original_keep = set(json.loads((out/'live/joint_candidates.json').read_text())['keep'])
    if not set(excluded).issubset(original_keep):
        raise ValueError('Excluded IDs must be selected in the live plan')
    for stage in ('fresh', 'cached'):
        keep = set(json.loads((out/stage/'joint_candidates.json').read_text())['keep'])
        if keep.intersection(excluded):
            raise ValueError('Native retry did not exclude selected IDs: '+stage)
    for relative in (*FRESH_NATIVE_TABLES, 'joint_candidates.json', 'locality/final_plan.tcl', 'native_plan.tcl'):
        a, b = out/'fresh'/relative, out/'cached'/relative
        av = table(a) if a.suffix == '.tsv' else json.loads(a.read_text()) if a.suffix == '.json' else a.read_bytes()
        bv = table(b) if b.suffix == '.tsv' else json.loads(b.read_text()) if b.suffix == '.json' else b.read_bytes()
        if av != bv:
            raise ValueError('Native fresh/cached retry admission differs: '+relative)
        evidence.append(dict(name=relative, fresh_sha256=cache.sha(a), cached_sha256=cache.sha(b)))
    hashes = cache.code_inventory(code)
    if json.loads((out/'source_manifest.json').read_text()) != hashes:
        raise ValueError('Probe source changed after execution')
    result = dict(schema=PROOF_SCHEMA, status='PASS', source_hashes=hashes,
                  live_vs_reopened_static_equivalent=True, retry_finish_equivalent=True,
                  fresh_native_inputs_and_timing_equivalent=True, retry_native_plan_equivalent=True,
                  checkpoint_sha256=cache.sha(out/'base/pre_route.dcp'), evidence=evidence,
                  excluded=excluded, native_discovery_seconds=runtimes,
                  cache_restore_seconds=receipt['seconds'],
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
