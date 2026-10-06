"""Conservative phase reservations; paused processes retain all resident memory."""
import hashlib
import json
import os
from pathlib import Path
import time

BUDGETS = {'startup': 32.0, 'seed': 32.0, 'base': 40.0, 'generic': 54.0, 'reopen': 32.0}
HEADROOM = 4.0


def write(path, value):
    path = Path(path)
    temp = path.with_name(path.name + '.' + str(os.getpid()) + '.tmp')
    temp.write_text(json.dumps(value, indent=2) + '\n')
    temp.replace(path)


def required_available(requested, own_rss, other_reservations, headroom=HEADROOM):
    values = [requested, own_rss, headroom] + [v for pair in other_reservations for v in pair]
    if any(v < 0 for v in values):
        raise ValueError('Negative memory value')
    return max(0.0, requested - own_rss) + sum(max(0.0, budget-rss) for budget, rss in other_reservations) + headroom


def fingerprint(pid):
    p = Path('/proc') / str(pid)
    # The comm field may contain spaces; use the closing parenthesis.
    rest = (p/'stat').read_text().rsplit(')', 1)[1].split()
    return {'pid': pid, 'start_ticks': int(rest[19]), 'state': rest[0],
            'cmd_sha256': hashlib.sha256((p/'cmdline').read_bytes()).hexdigest(),
            'command': (p/'cmdline').read_bytes().replace(b'\0', b' ').decode(errors='replace'),
            'cwd': os.readlink(p/'cwd')}


def same_process(saved, current):
    return all(saved[k] == current[k] for k in ('pid', 'start_ticks', 'cmd_sha256', 'cwd'))


def alive(saved):
    try:
        current = fingerprint(saved['pid'])
        return same_process(saved, current) and current['state'] not in ('Z', 'X')
    except (FileNotFoundError, ProcessLookupError, PermissionError):
        return False


def snapshot():
    rows = {}
    for p in Path('/proc').iterdir():
        if not p.name.isdigit():
            continue
        try:
            fields = dict((line.split(':')[0], int(line.split()[1])) for line in (p/'status').read_text().splitlines()
                          if line.startswith(('PPid:', 'VmRSS:')))
            rows[int(p.name)] = {'ppid': fields['PPid'], 'rss': fields.get('VmRSS', 0)/1024**2}
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            pass
    return rows


def descendants(pid, rows):
    owned = {pid}
    while True:
        found = {p for p, row in rows.items() if row['ppid'] in owned}
        if found <= owned:
            return owned
        owned.update(found)


def owned_rss(pid, rows):
    return sum(rows[p]['rss'] for p in descendants(pid, rows) if p in rows)


def lease_valid(grant, request, now):
    return (grant.get('nonce') == request['nonce'] and grant.get('stage') == request['stage']
            and grant.get('granted') is True and grant.get('expires', 0) >= now)


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except FileNotFoundError:
        return {} if default is None else default
