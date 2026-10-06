"""Admission only; never stop either experiment or unrelated processes."""
from pathlib import Path
import json, os, sys, time


def snapshot(root, mode, own_pid):
    policy = json.loads((root / 'memory_policy.json').read_text())
    available = int(next(s.split()[1] for s in Path('/proc/meminfo').read_text().splitlines()
                         if s.startswith('MemAvailable:'))) / 1024**2
    old_rss = 0.0
    old_alive = False
    old_processes = []
    for d in Path('/proc').iterdir():
        if not d.name.isdigit():
            continue
        try:
            cmd = (d / 'cmdline').read_bytes().replace(b'\0', b' ').decode(errors='replace')
            if policy['reference_root'] not in cmd or not ('unwrapped/lnx64.o/vivado' in cmd or 'run_trial.py' in cmd):
                continue
            old_alive = True
            rss = int(next(s.split()[1] for s in (d / 'status').read_text().splitlines()
                           if s.startswith('VmRSS:'))) / 1024**2
            old_rss += rss
            old_processes.append(dict(pid=int(d.name), rss_gib=rss))
        except (OSError, StopIteration, ValueError):
            continue
    try:
        own_rss = int(next(s.split()[1] for s in Path(f'/proc/{own_pid}/status').read_text().splitlines()
                           if s.startswith('VmRSS:'))) / 1024**2
    except (OSError, StopIteration):
        own_rss = 0.0
    old_growth = max(0.0, policy['reference_peak_gib'] - old_rss) if old_alive else 0.0
    budget = policy['prepare_peak_gib'] if mode == 'prepare' else policy['physical_peak_gib']
    required = old_growth + max(0.0, budget - own_rss) + policy['reserve_gib']
    return dict(time=time.time(), mode=mode, admitted=available >= required,
                available_gib=available, required_free_gib=required,
                reference_growth_reserved_gib=old_growth, own_rss_gib=own_rss,
                reference_processes=old_processes, own_peak_budget_gib=budget,
                reserve_gib=policy['reserve_gib'])


def main():
    root, out = map(Path, sys.argv[1:3])
    mode, own_pid = sys.argv[3], int(sys.argv[4])
    assert mode in ('prepare', 'physical')
    out.mkdir(parents=True, exist_ok=True)
    started = time.time()
    while True:
        state = snapshot(root, mode, own_pid)
        state['wait_seconds'] = time.time() - started
        path = out / f'memory_admission_{mode}.json'
        tmp = path.with_suffix('.tmp')
        tmp.write_text(json.dumps(state, indent=2) + '\n')
        tmp.replace(path)
        if state['admitted']:
            print(json.dumps(state))
            return
        time.sleep(20)


if __name__ == '__main__':
    main()
