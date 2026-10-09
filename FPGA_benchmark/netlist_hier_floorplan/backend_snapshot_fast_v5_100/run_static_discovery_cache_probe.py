"""Run three independent, read-only native cache-equivalence probes.

This harness never runs ECO, placement or routing and never enables production
cache reuse. The resulting source-bound proof can be admitted by run_case.py.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import time


def run(code, out, fixture, expected_sha256, vivado):
    spec = importlib.util.spec_from_file_location('cache_probe_verifier', code/'verify_static_discovery_cache_probe.py')
    verifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verifier)
    cache = verifier.module(code)
    try:
        out.relative_to(code)
    except ValueError:
        pass
    else:
        raise ValueError('Probe outputs must be outside the frozen source tree')
    if cache.sha(fixture) != expected_sha256:
        raise ValueError('Fixture checkpoint identity mismatch')
    source_hashes = cache.code_inventory(code)
    out.mkdir(parents=True, exist_ok=False)
    state = dict(status='RUNNING', fixture=str(fixture), fixture_sha256=expected_sha256,
                 source_hashes=source_hashes, stages=[], mode='read_only_native_discovery')
    cache.write(out/'probe_status.json', state)
    try:
        for stage in ('live', 'fresh', 'cached'):
            if source_hashes != cache.code_inventory(code):
                raise ValueError('Frozen probe source changed before '+stage)
            command = [str(vivado), '-mode', 'batch', '-notrace', '-source',
                       str(code/'native_static_discovery_cache_probe.tcl'),
                       '-log', str(out/(stage+'.log')), '-journal', str(out/(stage+'.jou')),
                       '-tclargs', str(code), str(out), stage, str(fixture)]
            state['stage'] = stage
            cache.write(out/'probe_status.json', state)
            begin = time.monotonic()
            with (out/(stage+'_console.log')).open('x') as log:
                result = subprocess.run(command, cwd=out, stdout=log, stderr=subprocess.STDOUT)
            state['stages'].append(dict(name=stage, returncode=result.returncode,
                                       seconds=time.monotonic()-begin, command=command))
            cache.write(out/'probe_status.json', state)
            if result.returncode:
                raise ValueError('Native '+stage+' probe failed; evidence preserved')
        if source_hashes != cache.code_inventory(code):
            raise ValueError('Frozen probe source changed during execution')
        if cache.sha(fixture) != expected_sha256:
            raise ValueError('Fixture checkpoint changed during execution')
        proof = verifier.compare(code, out)
        state.update(status='PASS', evidence=str(out/'native_static_discovery_cache_evidence.json'),
                     source_identity_unchanged=True, fixture_identity_unchanged=True,
                     native_discovery_seconds=proof['native_discovery_seconds'])
    except Exception as error:
        state.update(status='ERROR', error=str(error))
        cache.write(out/'probe_status.json', state)
        raise
    cache.write(out/'probe_status.json', state)
    return state


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--code', type=Path, default=Path(__file__).resolve().parent)
    ap.add_argument('--out', required=True, type=Path)
    ap.add_argument('--fixture-dcp', required=True, type=Path)
    ap.add_argument('--expected-fixture-sha256', required=True)
    ap.add_argument('--vivado', required=True, type=Path)
    args = ap.parse_args()
    result = run(args.code.resolve(), args.out.resolve(), args.fixture_dcp.resolve(),
                 args.expected_fixture_sha256, args.vivado.resolve())
    print(json.dumps({key: value for key, value in result.items() if key != 'source_hashes'}))


if __name__ == '__main__':
    main()
