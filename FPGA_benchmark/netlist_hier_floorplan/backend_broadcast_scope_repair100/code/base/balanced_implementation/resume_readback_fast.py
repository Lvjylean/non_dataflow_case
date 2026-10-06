"""Resume only independent readback after a completed physical implementation."""
import argparse
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda: f.read(8 * 1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()


def main(root):
    root = root.resolve()
    case = root / 'modules11'
    impl = case / 'implementation_01'
    final = impl / 'post_route.dcp'
    assert not (case / 'result.json').exists()
    assert (case / 'implementation.exit').read_text().strip() == '0'
    assert (impl / 'complete.txt').exists()
    state = json.loads((root / 'status.json').read_text())
    assert state['stage'] == 'STOPPED_WITH_RETAINED_EVIDENCE'
    with (root / 'status_before_readback02.json').open('x') as f:
        json.dump(state, f, indent=2)
    code = root / 'code_seed'
    for name in ('balanced_implementation/reopen.tcl', 'balanced_implementation/adapter.tcl', 'fanout96/core.tcl'):
        assert digest(code / name) == digest(root / 'code_v1' / name)
    assert (code / 'connection_floorplan/audit.tcl').is_file()
    for manifest_path in root.glob('code_manifest*.json'):
        folder = root / ('code' + manifest_path.stem.removeprefix('code_manifest'))
        for name, sha in json.loads(manifest_path.read_text()).items():
            assert digest(folder / name) == sha
    manifest = json.loads((case / 'input/manifest.json').read_text())
    source = Path(json.loads((root / 'input_validation.json').read_text())['source'])

    def validate():
        assert digest(manifest['input_dcp']) == manifest['input_sha256']
        for name, sha in manifest['files'].items():
            assert digest(source / name) == digest(case / 'input' / name) == sha

    validate()
    before = digest(final)
    state.update(pid=os.getpid(), readback_code=str(code), previous_error=state.pop('error', None))

    def note(stage, **extra):
        state.update(stage=stage, updated_epoch=time.time(), **extra)
        temp = root / 'status.tmp'
        temp.write_text(json.dumps(state, indent=2) + '\n')
        temp.replace(root / 'status.json')
        print(json.dumps(state), flush=True)

    try:
        note('reopen02')
        started = time.time()
        with (case / 'reopen02.log').open('x') as f:
            p = subprocess.Popen(['vivado', '-mode', 'batch', '-log', 'reopen02_vivado.log',
                                  '-journal', 'reopen02.jou', '-source', str(code / 'balanced_implementation/reopen.tcl'),
                                  '-tclargs', str(case / 'input'), str(final), str(case / 'reopened02')],
                                 cwd=case, stdout=f, stderr=subprocess.STDOUT)
            note('reopen02', active_wrapper_pid=p.pid)
            rc = p.wait()
        (case / 'reopen02.exit').write_text(str(rc) + '\n')
        state['stages']['reopen02'] = dict(start=started, end=time.time(), return_code=rc)
        assert rc == 0, f'Readback exited {rc}'
        assert (case / 'reopened02/complete.txt').exists()
        assert digest(final) == before
        validate()
        result = dict(status='IMPLEMENTED_AND_REOPENED', dcp=str(final), bytes=final.stat().st_size,
                      sha256=before, input_sha256_unchanged=True, frozen_exports_unchanged=True,
                      implementation=impl.name, audit='reopened02', stages=['implementation', 'reopen02'],
                      finished_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                      acceptance='Independent timing/fanout/spill annotations; <100 logical stop.',
                      flow='batched_identity_tree', implementation_script='implement_quick.tcl',
                      code=str(root / 'code_v1/balanced_implementation'), readback_code=str(code),
                      readback_recovery='Initial readback exited before opening DCP because code_v1 omitted connection_floorplan/audit.tcl. Resumed only readback using identical frozen scripts and the existing complete dependency snapshot; physical run was not repeated.')
        with (case / 'result.json').open('x') as f:
            json.dump(result, f, indent=2)
            f.write('\n')
        note('IMPLEMENTED_AND_REOPENED', result=result, active_wrapper_pid=None)
    except Exception as error:
        note('STOPPED_WITH_RETAINED_EVIDENCE', error=str(error), active_wrapper_pid=None)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('run', type=Path)
    main(parser.parse_args().run)
