"""Run one frozen floorplan through verified batched ECO and physical readback."""
import argparse
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def run(root, attempt="01", validation=None, implementation_script="implement_fast.tcl"):
    root = root.resolve()
    case = root / 'modules11'
    implementation_stage = 'implementation' if attempt == '01' else 'implementation' + attempt
    reopen_stage = 'reopen' if attempt == '01' else 'reopen' + attempt
    audit_name = 'reopened' if attempt == '01' else 'reopened' + attempt
    code = Path(__file__).resolve().parent
    manifest = json.loads((case / 'input/manifest.json').read_text())
    source = Path(json.loads((root / 'input_validation.json').read_text())['source'])
    state = dict(pid=os.getpid(), run=str(root), source=str(source), code=str(code), stages={})

    def note(stage, **extra):
        state.update(stage=stage, updated_epoch=time.time(), **extra)
        temp = root / 'status.tmp'
        temp.write_text(json.dumps(state, indent=2) + '\n')
        temp.replace(root / 'status.json')
        print(json.dumps(state), flush=True)

    def validate_inputs():
        assert digest(manifest['input_dcp']) == manifest['input_sha256']
        for path, sha in manifest['files'].items():
            assert digest(case / 'input' / path) == sha
            assert digest(source / path) == sha

    def execute(stage, script, arguments):
        note(stage)
        started = time.time()
        command = ['vivado', '-mode', 'batch', '-log', stage + '_vivado.log',
                   '-journal', stage + '.jou', '-source', str(code / script),
                   '-tclargs', *map(str, arguments)]
        with (case / (stage + '.log')).open('x') as log:
            p = subprocess.Popen(command, cwd=case, stdout=log, stderr=subprocess.STDOUT)
            note(stage, active_wrapper_pid=p.pid)
            rc = p.wait()
        (case / (stage + '.exit')).write_text(str(rc) + '\n')
        state['stages'][stage] = dict(start=started, end=time.time(), return_code=rc)
        if rc:
            raise RuntimeError(f'{stage} exited {rc}; original evidence retained')

    try:
        # Fail before physical implementation if its later readback dependencies
        # were omitted from a frozen deployment bundle.
        for relative in ('reopen.tcl', 'adapter.tcl', '../fanout96/core.tcl',
                         '../connection_floorplan/audit.tcl', implementation_script):
            assert (code / relative).is_file(), f'Missing execution dependency: {relative}'
        note('WAITING_FOR_SEED')
        while not (case / 'seed.exit').exists():
            time.sleep(15)
        assert (case / 'seed.exit').read_text().strip() == '0'
        assert (root / 'smoke_fast_01/smoke.exit').read_text().strip() == '0'
        assert (root / 'smoke_fast_01/PASS.txt').exists()
        if validation:
            v = root / validation
            assert (v / 'smoke.exit').read_text().strip() == '0'
            assert (v / 'profile.exit').read_text().strip() == '0'
            assert (v / 'real/PASS.txt').exists()
        validate_inputs()
        seed = case / 'seed_01'
        impl = case / ('implementation_' + attempt)
        execute(implementation_stage, implementation_script,
                [case / 'input', seed / 'seed_place.dcp', impl, 'seed', seed])
        assert (impl / 'complete.txt').exists()
        final = impl / 'post_route.dcp'
        final_sha = digest(final)
        execute(reopen_stage, 'reopen.tcl', [case / 'input', final, case / audit_name])
        assert (case / audit_name / 'complete.txt').exists()
        assert digest(final) == final_sha
        validate_inputs()
        result = dict(status='IMPLEMENTED_AND_REOPENED', dcp=str(final),
                      bytes=final.stat().st_size, sha256=final_sha,
                      input_sha256_unchanged=True, frozen_exports_unchanged=True,
                      implementation=impl.name, audit=audit_name,
                      stages=[implementation_stage, reopen_stage],
                      finished_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                      acceptance='Independent timing/fanout/spill annotations; <100 logical stop.',
                      flow='batched_identity_tree', implementation_script=implementation_script, code=str(code))
        (case / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
        note('IMPLEMENTED_AND_REOPENED', active_wrapper_pid=None, result=result)
    except Exception as error:
        note('STOPPED_WITH_RETAINED_EVIDENCE', error=str(error), active_wrapper_pid=None)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('run', type=Path)
    parser.add_argument('--attempt', default='01')
    parser.add_argument('--validation')
    parser.add_argument('--implementation-script', choices=['implement_fast.tcl', 'implement_quick.tcl'], default='implement_fast.tcl')
    args = parser.parse_args()
    run(args.run, args.attempt, args.validation, args.implementation_script)
