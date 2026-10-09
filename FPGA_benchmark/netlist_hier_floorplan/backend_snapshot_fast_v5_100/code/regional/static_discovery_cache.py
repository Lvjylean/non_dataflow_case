"""Checkpoint-bound static discovery reuse for the single timing-guard retry.

Only immutable inventory and prepare outputs are cached.  Native template/STA,
finish admission, live edit boundaries and every post-edit check remain fresh.
"""
import argparse
import hashlib
import json
from pathlib import Path
import time

FILES = ('cells.tsv', 'edges.tsv', 'diagnostics.tsv', 'metadata.tsv',
         'proposals.json', 'requests.tcl')
SCHEMA = 'locality-static-discovery-cache-v1'
PARAMETERS = dict(min_effective=16, max_candidates=1024, cone_budget=256,
                  branch_limit=96, cone_max_cells=128)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def write(path, data):
    path = Path(path)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(data, sort_keys=True, indent=2) + '\n')
    temporary.replace(path)


def code_inventory(root):
    root = Path(root).resolve()
    return {str(p.relative_to(root)): sha(p) for p in root.rglob('*')
            if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc'}


def make_context(checkpoint, source_root, source_manifest, version, part, clocks, producer):
    checkpoint = Path(checkpoint).resolve()
    root = Path(source_root).resolve()
    manifest = Path(source_manifest).resolve()
    expected = json.loads(manifest.read_text())
    if not expected or expected != code_inventory(root):
        raise ValueError('complete_source_inventory_mismatch')
    if not version or not part or not clocks or producer not in {'live_base', 'reopened_base'}:
        raise ValueError('missing_native_context')
    return dict(schema=SCHEMA, phase='before_locality_discovery_before_generic_ECO',
                checkpoint=str(checkpoint), checkpoint_sha256=sha(checkpoint),
                checkpoint_bytes=checkpoint.stat().st_size,
                source_root=str(root), source_manifest=str(manifest),
                source_manifest_sha256=sha(manifest), source_hashes=expected,
                vivado_version=version, part=part, clocks=clocks,
                prepare_parameters=PARAMETERS, producer_state=producer)


def key(context):
    if context.get('producer_state') not in {'live_base', 'reopened_base'}:
        raise ValueError('unknown_cache_producer_state')
    if context.get('schema') != SCHEMA or context.get('prepare_parameters') != PARAMETERS:
        raise ValueError('unknown_static_cache_schema_or_parameters')
    return {k: v for k, v in context.items() if k != 'producer_state'}


def revalidate(context):
    current = make_context(context['checkpoint'], context['source_root'], context['source_manifest'],
                           context['vivado_version'], context['part'], context['clocks'],
                           context['producer_state'])
    if current != context:
        raise ValueError('context_changed_during_capture')


def validate_output_headers(folder):
    folder = Path(folder)
    for name in FILES:
        if not (folder/name).is_file() or not (folder/name).stat().st_size:
            raise ValueError('missing_static_output:' + name)
    lines = (folder/'metadata.tsv').read_text().splitlines()
    if not lines or lines[0] != 'key\tvalue':
        raise ValueError('invalid_inventory_metadata')
    rows = [line.split('\t', 1) for line in lines[1:]]
    metadata = dict(rows)
    if len(metadata) != len(rows):
        raise ValueError('duplicate_inventory_metadata')
    if metadata.get('schema') != 'locality-inventory-v1' or metadata.get('status') != 'PASS':
        raise ValueError('inventory_not_complete')
    if json.loads((folder/'proposals.json').read_text()).get('schema') != 'broadcast-locality-v1':
        raise ValueError('invalid_prepare_schema')


def validate_outputs(folder):
    folder = Path(folder)
    validate_output_headers(folder)
    return {name: dict(sha256=sha(folder/name), bytes=(folder/name).stat().st_size) for name in FILES}


def copy_hashed(source, target):
    """Copy and hash the source in one pass; the destination is checked separately."""
    digest = hashlib.sha256()
    size = 0
    with Path(source).open('rb') as reader, Path(target).open('xb') as writer:
        for block in iter(lambda: reader.read(8 * 1024 * 1024), b''):
            digest.update(block)
            size += len(block)
            writer.write(block)
    return dict(sha256=digest.hexdigest(), bytes=size)


def publish(folder):
    folder = Path(folder)
    context = json.loads((folder/'static_context.json').read_text())
    revalidate(context)
    data = dict(schema=SCHEMA, status='COMPLETE', context=context, files=validate_outputs(folder))
    write(folder/'static_cache.json', data)
    return data


def restore(source, target):
    """Return MISS on any invalid cache; do not publish partial restored files."""
    begin = time.monotonic()
    source, target = Path(source), Path(target)
    temporary = []
    installed = []
    try:
        current = json.loads((target/'static_context.json').read_text())
        saved = json.loads((source/'static_cache.json').read_text())
        if saved.get('schema') != SCHEMA or saved.get('status') != 'COMPLETE':
            raise ValueError('cache_not_complete')
        if current.get('producer_state') != 'reopened_base':
            raise ValueError('cache_reuse_requires_reopened_base')
        if key(current) != key(saved['context']):
            raise ValueError('cache_context_mismatch')
        revalidate(current)
        validate_output_headers(source)
        expected = saved.get('files')
        if not isinstance(expected, dict) or set(expected) != set(FILES):
            raise ValueError('cached_output_manifest_mismatch')
        if any((target/name).exists() for name in FILES):
            raise ValueError('target_static_outputs_already_exist')
        # Copy to private temporaries, then recheck each byte before publication.
        observed = {}
        for name in FILES:
            tmp = target/(name + '.cache.tmp')
            if tmp.exists():
                raise ValueError('stale_cache_temporary')
            temporary.append(tmp)
            observed[name] = copy_hashed(source/name, tmp)
            if observed[name] != expected[name]:
                raise ValueError('cached_output_hash_mismatch:' + name)
            if sha(tmp) != observed[name]['sha256'] or tmp.stat().st_size != observed[name]['bytes']:
                raise ValueError('cache_copy_changed:' + name)
        # A long copy must not publish data after its checkpoint/source identity changed.
        revalidate(current)
        for name, tmp in zip(FILES, temporary):
            tmp.replace(target/name)
            installed.append(target/name)
        result = dict(status='HIT', source=str(source.resolve()), context=current,
                      files=observed, seconds=time.monotonic()-begin)
    except (OSError, ValueError, KeyError, TypeError) as error:
        for path in temporary + installed:
            path.unlink(missing_ok=True)
        result = dict(status='MISS', source=str(source), reason=str(error),
                      seconds=time.monotonic()-begin)
    write(target/'static_cache_restore.json', result)
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('mode', choices=('begin', 'publish', 'restore'))
    ap.add_argument('folder', type=Path)
    ap.add_argument('--source', type=Path)
    ap.add_argument('--checkpoint', type=Path)
    ap.add_argument('--source-root', type=Path)
    ap.add_argument('--source-manifest', type=Path)
    ap.add_argument('--vivado-version')
    ap.add_argument('--part')
    ap.add_argument('--clocks')
    ap.add_argument('--producer', choices=('live_base', 'reopened_base'))
    args = ap.parse_args()
    if args.mode == 'begin':
        context = make_context(args.checkpoint, args.source_root, args.source_manifest,
                               args.vivado_version, args.part, args.clocks, args.producer)
        write(args.folder/'static_context.json', context)
        print('CONTEXT_READY')
    elif args.mode == 'publish':
        publish(args.folder)
        print('PUBLISHED')
    else:
        if args.source is None:
            ap.error('restore requires --source')
        print(restore(args.source, args.folder)['status'])


if __name__ == '__main__':
    main()
