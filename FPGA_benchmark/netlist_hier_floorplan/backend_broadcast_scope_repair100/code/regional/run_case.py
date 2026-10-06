#!/usr/bin/env python3
"""Independent accelerated FF/CE and regional fanout flow with bounded checkpoint recovery."""
import argparse
import hashlib
import json
import re
import subprocess
import time
from pathlib import Path


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda: f.read(8 * 1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()


def write_json(path, value):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, indent=2) + '\n')
    tmp.replace(path)


def timing(path):
    lines = path.read_text().splitlines()
    for i, line in enumerate(lines):
        if 'WNS(ns)' in line and 'WHS(ns)' in line:
            for row in lines[i+1:i+8]:
                v = row.split()
                if len(v) >= 8:
                    try:
                        return dict(wns_ns=float(v[0]), tns_ns=float(v[1]),
                                    setup_failing=int(v[2]), whs_ns=float(v[4]),
                                    ths_ns=float(v[5]), hold_failing=int(v[6]))
                    except ValueError:
                        pass
    raise ValueError(f'Missing timing table: {path}')


def slacks(path):
    v = [float(x) for x in re.findall(r'Slack\s+\([^)]*\)\s*:\s*([-+0-9.]+)ns', path.read_text())]
    return dict(count=len(v), min_slack_ns=min(v) if v else None)


def run_stage(args, code, root, state, stage, checkpoint, out, mode, plan):
    """Resume only a typed protection handoff, once per boundary, in a new process."""
    recovered = {x['boundary'] for x in state.get('recoveries', [])} if mode.startswith('_resume_') else set()
    attempt = stage
    while True:
        state['stage'] = attempt
        state['status'] = 'RECOVERING' if recovered else 'RUNNING'
        write_json(root / 'status.json', state)
        start = time.time()
        with (root / f'{attempt}_console.log').open('w') as log:
            result = subprocess.run([args.vivado, '-mode', 'batch', '-source', str(code / 'run.tcl'),
                '-log', str(root / f'{attempt}.log'), '-journal', str(root / f'{attempt}.jou'),
                '-tclargs', str(checkpoint), str(out), mode, str(plan) if plan else '',
                str(args.min_fanout), str(args.path_limit), args.selection,
                str(int(args.regional == 'on')), str(args.regional_min_fanout),
                str(args.regional_branch_limit), str(args.region_width), str(args.region_height),
                str(args.regional_max_luts), args.legacy_eco, getattr(args, 'execution_profile', 'fast')], cwd=root, stdout=log, stderr=subprocess.STDOUT)
        state['stages'].append(dict(stage=attempt, return_code=result.returncode,
                                    seconds=time.time()-start))
        for recovery in state.get('recoveries', []):
            receipt = out / 'recovery' / f"{recovery['boundary']}_accepted.txt"
            if receipt.is_file():
                recovery['acceptance'] = 'PASS: full checks in fresh Vivado process'
        verify_publications(out, state)
        write_json(root / 'status.json', state)
        if result.returncode == 0:
            if mode != 'inspect' and not (out / 'complete.txt').is_file():
                raise RuntimeError(f'{attempt} exited without completion evidence')
            return
        if result.returncode != 75 or stage != 'implementation':
            raise RuntimeError(f'{attempt} returned {result.returncode}')
        boundary = (out / 'recovery/pending.txt').read_text().strip()
        if boundary not in {'post_place', 'resume_place', 'post_route'} or boundary in recovered:
            raise RuntimeError(f'Unsupported or repeated checkpoint recovery: {boundary!r}')
        checkpoint = out / 'recovery' / f'{boundary}.dcp'
        plan = out / 'plan.tcl'
        for artifact in (checkpoint, plan):
            if not artifact.is_file() or artifact.stat().st_size == 0:
                raise RuntimeError(f'Missing recovery artifact: {artifact}')
        recovered.add(boundary)
        state.setdefault('recoveries', []).append(dict(boundary=boundary,
            checkpoint=str(checkpoint), checkpoint_sha256=sha(checkpoint),
            plan_sha256=sha(plan), acceptance='Required in fresh Vivado process'))
        mode = f'_resume_{boundary}'
        attempt = f'{stage}_resume_{boundary}'


def verify_publications(out, state):
    """Bind each reused formal checkpoint to its previously recorded recovery hash."""
    publications = state.setdefault('checkpoint_publications', [])
    seen = {x['target'] for x in publications}
    for receipt in sorted((out / 'recovery').glob('*_published.tsv')):
        lines = receipt.read_text().splitlines()
        if len(lines) != 2 or lines[0] != 'boundary\tsource\ttarget\tbytes':
            raise ValueError(f'Malformed checkpoint publication: {receipt}')
        boundary, source, target, size = lines[1].split('\t')
        source, target = Path(source), Path(target)
        if boundary not in {'post_place', 'post_route'} or source.resolve() != (out / 'recovery' / f'{boundary}.dcp').resolve() or target.resolve() != (out / f'{boundary}.dcp').resolve():
            raise ValueError('Unexpected checkpoint publication paths')
        if str(target) in seen:
            continue
        recovery = next((x for x in state.get('recoveries', []) if x['boundary'] == boundary), None)
        if not recovery or not recovery['acceptance'].startswith('PASS:'):
            raise ValueError('Unaccepted checkpoint publication')
        digest = sha(target)
        if target.stat().st_size != int(size) or digest != recovery['checkpoint_sha256']:
            raise ValueError('Published checkpoint differs from recovery checkpoint')
        publications.append(dict(boundary=boundary, source=str(source), target=str(target),
                                 sha256=digest, verification='PASS: exact diagnostic bytes'))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--execution-profile', choices=['fast', 'reference'], default='fast',
                    help='fast batches ECO operations and reuses verified recovery checkpoints; reference keeps the common execution order.')
    ap.add_argument('--input', type=Path, required=True)
    ap.add_argument('--expected-sha256', required=True)
    ap.add_argument('--work-root', type=Path, required=True)
    ap.add_argument('--mode', choices=['run', 'inspect', 'edit', 'place', 'route'], default='run')
    ap.add_argument('--plan', type=Path)
    ap.add_argument('--baseline-dir', type=Path)
    ap.add_argument('--min-fanout', type=int, default=16)
    ap.add_argument('--path-limit', type=int, default=1000)
    ap.add_argument('--selection', choices=['structure', 'timing'], default='structure')
    ap.add_argument('--input-stage', choices=['placed', 'routed', 'unspecified'], default='unspecified')
    ap.add_argument('--regional', choices=['on', 'off'], default='on')
    ap.add_argument('--regional-min-fanout', type=int, default=16)
    ap.add_argument('--regional-branch-limit', type=int, default=96)
    ap.add_argument('--region-width', type=int, default=2)
    ap.add_argument('--region-height', type=int, default=2)
    ap.add_argument('--regional-max-luts', type=int, default=50000)
    ap.add_argument('--legacy-eco', choices=['run', 'skip'], default='run',
                    help='Keep run for the original FF/CE procedure; skip on an already processed input.')
    ap.add_argument('--vivado', default='/home/lduac/Software/Xilinx/Vivado/2023.2/bin/vivado')
    args = ap.parse_args()
    if not 2 <= args.regional_branch_limit <= 96 or args.regional_min_fanout < 2:
        ap.error('Regional branch limit must be 2..96 and min fanout >=2')
    if min(args.region_width, args.region_height, args.regional_max_luts) <= 0:
        ap.error('Regional dimensions and budget must be positive')
    if args.mode in ['place', 'route'] and not args.baseline_dir:
        ap.error('Resume place/route requires --baseline-dir')
    root = args.work_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    if (root / 'status.json').exists() or (root / 'implementation').exists():
        raise FileExistsError('Use a fresh work directory')
    if args.mode in ['edit', 'place', 'route'] and not args.plan:
        ap.error('Resume requires --plan')
    if sha(args.input) != args.expected_sha256:
        raise ValueError('Input checkpoint SHA256 mismatch')
    code = Path(__file__).resolve().parent
    state = dict(status='RUNNING', execution_profile=args.execution_profile, input=str(args.input), input_sha256=args.expected_sha256,
                 mode=args.mode, selection=args.selection, input_stage=args.input_stage, regional=args.regional, legacy_eco=args.legacy_eco, start=time.time(), stages=[])
    write_json(root / 'code_manifest.json', {p.name: sha(p) for p in code.iterdir() if p.is_file()})
    write_json(root / 'status.json', state)
    impl = root / 'implementation'
    reopen = root / 'reopened'
    stages = [('implementation', args.input, impl, args.mode, args.plan)]
    if args.mode != 'inspect':
        stages.append(('reopen', impl / 'post_route.dcp', reopen, 'reopen', impl / 'plan.tcl'))
    try:
        for stage, checkpoint, out, mode, plan in stages:
            run_stage(args, code, root, state, stage, checkpoint, out, mode, plan)
        if args.mode != 'inspect':
            baseline = args.baseline_dir or impl / 'baseline'
            before = timing(baseline / 'timing_summary.rpt')
            after = timing(impl / 'post_route/timing_summary.rpt')
            reopened = timing(reopen / 'timing_summary.rpt')
            if after != reopened:
                raise ValueError('Independent reopened timing differs')
            families = {}
            for name in ['data_broadcast', 'data_input', 'data_enable', 'local_ce', 'existing_ce']:
                a, b = baseline / f'{name}.rpt', reopen / f'{name}.rpt'
                if a.exists() and b.exists():
                    families[name] = dict(before=slacks(a), after=slacks(b))
            comparison = dict(baseline=before, post_route=after, reopened=reopened,
                baseline_kind=args.input_stage,
                delta_wns_ns=round(after['wns_ns']-before['wns_ns'], 3), families=families,
                dcp=str(impl/'post_route.dcp'), dcp_sha256=sha(impl/'post_route.dcp'))
            write_json(root/'comparison.json', comparison)
        state['status'] = 'INSPECTED' if args.mode == 'inspect' else ('COMPLETE_TIMING_PASS' if after['setup_failing'] == 0 and after['hold_failing'] == 0 else 'COMPLETE_TIMING_FAIL')
    except Exception as e:
        state.update(status='ERROR', error=repr(e))
        raise
    finally:
        state.update(end=time.time(), seconds=time.time()-state['start'],
                     input_unchanged=sha(args.input)==args.expected_sha256)
        write_json(root/'status.json', state)
        print(json.dumps(state), flush=True)


if __name__ == '__main__':
    main()
