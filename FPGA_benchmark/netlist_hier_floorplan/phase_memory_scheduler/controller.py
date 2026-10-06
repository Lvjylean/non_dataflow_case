"""Adopt the running job, then admit the queued job at bounded native phase gates."""
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import traceback
from policy import BUDGETS, HEADROOM, alive, descendants, fingerprint, owned_rss, read_json, required_available, same_process, snapshot, write


def compact_result(value):
    return {k: value.get(k) for k in ('status', 'compile_scope', 'timing', 'gates', 'compile_seconds',
                                     'dcp', 'dcp_sha256', 'fanout')} if value else {}


def append(path, value):
    with path.open('a') as f:
        f.write(json.dumps(dict(time=time.time(), **value))+'\n')


def assert_queued_inactive(root, proc_root=Path('/proc')):
    for p in proc_root.iterdir():
        if not p.name.isdigit() or int(p.name) == os.getpid():
            continue
        try:
            command = (p/'cmdline').read_bytes().replace(b'\0', b' ').decode(errors='replace')
            cwd = os.readlink(p/'cwd')
            if str(root) in command or cwd == str(root) or cwd.startswith(str(root)+'/'):
                raise RuntimeError('Queued experiment already has a process: '+p.name)
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            pass


def owner_budget(job):
    r = Path(job.get('current_root', job['run_root']))
    status = read_json(r/'status.json')
    if status.get('stage') == 'reopen' and (r/'generic/implementation/post_route.dcp').is_file():
        return BUDGETS['reopen']
    return BUDGETS['generic']


def native_processes(job, saved_controller, rows):
    if not alive(saved_controller):
        return []
    root = job.get('current_root', job['run_root'])
    found = []
    for pid in descendants(saved_controller['pid'], rows):
        try:
            current = fingerprint(pid)
            if ('/unwrapped/lnx64.o/vivado ' in current['command'] and
                    (current['cwd'] == root or current['cwd'].startswith(root+'/')) and
                    root in current['command']):
                found.append(current)
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            pass
    return found


def signal_native(saved, sig, root):
    current = fingerprint(saved['pid'])
    if (not same_process(saved, current) or '/unwrapped/lnx64.o/vivado ' not in current['command']
            or not (current['cwd'] == root or current['cwd'].startswith(root+'/'))):
        raise RuntimeError('Refusing to signal an unverified native process')
    os.kill(saved['pid'], sig)


def main():
    here = Path(__file__).resolve().parent
    c = read_json(here/'config.json')
    root, second_root = Path(c['pair_root']), Path(c['second_root'])
    lock = (root/'phase_scheduler.lock').open('a+')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    if (here/'handoff.json').exists():
        raise RuntimeError('Existing scheduler handoff requires explicit recovery admission')
    spec = importlib.util.spec_from_file_location('frozen_phase_flow', Path(c['source'])/'run_case.py')
    flow = importlib.util.module_from_spec(spec); spec.loader.exec_module(flow)
    validation = read_json(root/'integration_validation.json')
    flow.validate_locality_admission(validation, Path(c['source']))
    if flow.sha(Path(c['post_opt'])) != c['post_opt_sha256']:
        raise RuntimeError('Clean post-opt changed')
    initial = read_json(root/'series_state.json')
    if (initial['controller_pid'] != c['old_scheduler']['pid'] or
            [j['name'] for j in initial['jobs']] != ['affinity01', 'affinity02'] or
            initial['jobs'][0]['status'] != 'RUNNING' or initial['jobs'][1]['status'] != 'QUEUED'):
        raise RuntimeError('Pair changed before handoff')
    if second_root.exists():
        raise RuntimeError('Queued output exists; do not duplicate its controller')
    assert_queued_inactive(second_root)
    for j in initial['jobs']:
        if flow.validate_floorplan(Path(j['floorplan']), c['post_opt_sha256'])['module_count'] != j['module_count']:
            raise RuntimeError('Floorplan changed')
    first_saved = fingerprint(initial['jobs'][0]['controller_pid'])
    if c['first_root'] not in first_saved['command'] or first_saved['cwd'] != str(root):
        raise RuntimeError('Running experiment owner differs')
    old = fingerprint(c['old_scheduler']['pid'])
    if not same_process(c['old_scheduler'], old) or old['cwd'] != str(root):
        raise RuntimeError('Scheduler PID was reused')
    # Save the full lineage before touching ownership. No physical process is stopped here.
    write(here/'series_before_handoff.json', initial)
    write(here/'adoption_prepared.json', dict(new_controller=fingerprint(os.getpid()),
        first_controller=first_saved, old_scheduler=old, source_hashes=flow.source_hashes(Path(c['source']))))
    handed_off = False
    paused = {}
    handles = {}
    logs = {}
    try:
        os.kill(old['pid'], signal.SIGSTOP)
        deadline = time.monotonic()+5
        while fingerprint(old['pid'])['state'] != 'T':
            if time.monotonic()>deadline:
                raise RuntimeError('Scheduler did not suspend')
            time.sleep(.05)
        state = read_json(root/'series_state.json')
        if state['jobs'][1]['status'] != 'QUEUED' or second_root.exists():
            raise RuntimeError('Second job raced with handoff')
        assert_queued_inactive(second_root)
        first, second = state['jobs']
        if first['controller_pid'] != first_saved['pid'] or not alive(first_saved):
            raise RuntimeError('First job changed during handoff')
        for job in state['jobs']:
            for prior in job.get('prior_attempts', []):
                if prior.get('result'):
                    prior['result'] = compact_result(prior['result'])
                    prior['full_result_archive'] = str(here/'series_before_handoff.json')
        registered = {'affinity01': first_saved}
        state.update(controller_pid=os.getpid(), scheduler_mode='phase_memory_v1',
                     previous_scheduler_suspended=old, handoff_time=time.time())
        write(here/'handoff.json', dict(status='ACTIVE', new_controller=fingerprint(os.getpid()),
            first_controller=first_saved, old_scheduler_suspended=old,
            original_physical_source_unchanged=True))
        handed_off = True
        append(here/'events.jsonl', dict(event='ADOPTED', first_pid=first_saved['pid'], old_scheduler_pid=old['pid']))
        gate = Path(c['gate_directory']); gate.mkdir(exist_ok=True)
        while True:
            rows = snapshot()
            for job in state['jobs']:
                name = job['name']; saved = registered.get(name)
                if saved is None:
                    continue
                active = alive(saved)
                if name in handles:
                    active = handles[name].poll() is None
                if not active and job['status'] == 'RUNNING':
                    r = Path(job.get('current_root', job['run_root']))
                    result = read_json(r/'result.json')
                    status = read_json(r/'status.json')
                    if name in handles:
                        rc = handles[name].returncode
                        logs.pop(name).close()
                    else:
                        rc = 0 if status.get('status') == 'COMPLETE_REVIEW_CRITERIA' and status.get('report_returncode') == 0 else 1
                    job.update(status=result.get('status', 'STOPPED_WITH_EVIDENCE'), returncode=rc,
                               ended_at=time.time(), result=compact_result(result))
                    append(here/'events.jsonl', dict(event='JOB_ENDED', name=name, returncode=rc, status=job['status']))
            running = [j for j in state['jobs'] if j['status'] == 'RUNNING']
            failures = [j for j in state['jobs'] if j.get('returncode', 0) != 0]
            rss = {j['name']: owned_rss(j['controller_pid'], rows) for j in running}
            available = next(int(l.split()[1])/1024**2 for l in Path('/proc/meminfo').read_text().splitlines() if l.startswith('MemAvailable:'))
            budgets = {'affinity01': owner_budget(first)} if first['status'] == 'RUNNING' else {}
            receipt = read_json(gate/'receipt.json')
            if second['status'] == 'RUNNING':
                budgets['affinity02'] = BUDGETS[receipt.get('stage', 'startup')]
            # Emergency freeze prevents further allocation; it never treats RSS as freed.
            target_names = [j['name'] for j in running if available < (8 if j['name']=='affinity02' else 4)]
            for job in running:
                name = job['name']; r = job.get('current_root', job['run_root'])
                if name in target_names and name not in paused:
                    targets = native_processes(job, registered[name], rows)
                    for saved in targets:
                        signal_native(saved, signal.SIGSTOP, r)
                    if targets:
                        paused[name] = dict(processes=targets, start=time.time())
                        append(here/'events.jsonl', dict(event='EMERGENCY_PAUSE', name=name, available_gib=available))
                elif name in paused and name not in target_names:
                    other = [(budget, rss.get(n, 0)) for n, budget in budgets.items() if n != name]
                    need = max(12, required_available(budgets[name], rss[name], other))
                    if available >= need:
                        for saved in paused[name]['processes']:
                            if alive(saved):
                                signal_native(saved, signal.SIGCONT, r)
                        waited = time.time()-paused[name]['start']
                        append(here/'events.jsonl', dict(event='EMERGENCY_RESUME', name=name, seconds=waited))
                        paused.pop(name)
            requested = read_json(gate/'request.json')
            admission = dict(time=time.time(), available_gib=available, active_rss_gib=rss,
                             reserved_gib=budgets, headroom_gib=HEADROOM,
                             paused={n:dict(start=v['start'], native_pids=[p['pid'] for p in v['processes']]) for n,v in paused.items()},
                             paused_memory_released=False, had_parallel=state.get('had_parallel', False))
            if requested and second['status'] == 'RUNNING':
                if requested['stage'] not in BUDGETS or requested['requested_gib'] != BUDGETS[requested['stage']]:
                    raise RuntimeError('Unknown phase reservation')
                other = [(v, rss.get(n, 0)) for n,v in budgets.items() if n != 'affinity02']
                need = required_available(requested['requested_gib'], rss.get('affinity02', 0), other)
                admission.update(required_available_gib=need, requested_stage=requested['stage'])
                granted = not failures and 'affinity02' not in paused and available >= need
                # Renew a lease for the exact request only; native work is never duplicated.
                write(gate/'grant.json', dict(nonce=requested['nonce'], stage=requested['stage'],
                    granted=granted, expires=time.time()+10, admission=admission))
                second.update(requested_stage=requested['stage'],
                    phase_state='ADMITTED' if receipt.get('nonce') == requested['nonce'] else ('ADMITTING' if granted else 'WAITING_MEMORY'),
                    phase_memory_required_gib=requested['requested_gib'])
            if second['status'] == 'QUEUED' and not failures:
                need = required_available(BUDGETS['startup'], 0, [(v,rss.get(n,0)) for n,v in budgets.items()])
                admission['required_available_gib'] = need
                if available >= need:
                    env = os.environ.copy()
                    for key in list(env):
                        if key.startswith(('COMPILEFAST_', 'JI_', 'BL_STATIC_CACHE_', 'AFF_RECOVERY_', 'PHASE_')) or key in ('BL_LOCALITY','EXPERIMENT_INPUT'):
                            env.pop(key)
                    cmd = ['python3',str(Path(c['source'])/'run_case.py'),'--input',c['post_opt'],
                        '--expected-sha256',c['post_opt_sha256'],'--floorplan',second['floorplan'],
                        '--period','6.5','--work-root',str(second_root),
                        '--validation-json',str(root/'integration_validation.json'),
                        '--case-name','GETRF affinity02 6.5 ns','--clock-port','ap_clk',
                        '--memory-required-gib','32','--joint-wns-policy','positive',
                        '--broadcast-locality','--timing-extraction','pin','--vivado',str(here/'vivado_entry.py')]
                    log = (root/'affinity02_phase_controller_console.log').open('x')
                    p = subprocess.Popen(cmd, cwd=root, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
                    handles['affinity02'] = p; logs['affinity02'] = log
                    registered['affinity02'] = fingerprint(p.pid)
                    second.update(status='RUNNING', controller_pid=p.pid, command=cmd, launched_at=time.time(), memory_admission=admission)
                    state['had_parallel'] = bool(first['status']=='RUNNING')
                    append(here/'events.jsonl', dict(event='LAUNCHED', name='affinity02', pid=p.pid, admission=admission))
            state.update(status='RUNNING' if running or second['status']=='RUNNING' else ('NEEDS_DIAGNOSIS' if failures else 'COMPLETE'),
                         updated=time.time(), memory_admission=admission)
            write(here/'ownership.json', dict(controllers=registered, paused=paused, updated=time.time()))
            write(root/'memory_admission.json', admission)
            write(root/'series_state.json', state)
            if all(j['status'] not in ('RUNNING','QUEUED') for j in state['jobs']):
                # All experiment controllers have ended; retire the old stopped scheduler.
                if alive(old):
                    os.kill(old['pid'], signal.SIGTERM)
                    os.kill(old['pid'], signal.SIGCONT)
                state.update(end=time.time(), elapsed_seconds=time.time()-state['start'])
                write(root/'series_state.json', state)
                return
            if failures and not running and second['status'] == 'QUEUED':
                raise RuntimeError('Shared flow diagnosis required before queued launch')
            time.sleep(3)
    except Exception:
        error = dict(status='NEEDS_DIAGNOSIS', traceback=traceback.format_exc(), time=time.time(),
                     adopted_experiments=handed_off, paused=paused)
        write(here/'error.json', error)
        # Before ownership changes, restore the original scheduler. Afterwards preserve
        # the registered jobs and gate state for a diagnosed, non-duplicating recovery.
        if not handed_off and alive(old):
            os.kill(old['pid'], signal.SIGCONT)
        raise


if __name__ == '__main__':
    main()
