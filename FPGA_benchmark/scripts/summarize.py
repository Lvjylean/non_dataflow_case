"""Validate archived reports; missing evidence never becomes a passing result."""
import json
import re
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
SERVER = '/Projects/jinyang/workspace/non_dataflow_crossSLR/case/FPGA_benchmark'
CASES = {'VTA': 'vta_buffered_u250_20260913_04', 'CNNA': 'cnna_buffered_u250_20260913_04'}

def read(path):
    return path.read_text(errors='replace') if path.is_file() else ''

def route(text):
    def count(label):
        match = re.search(r'# of ' + re.escape(label) + r'\.+\s*:\s*(\d+)', text)
        return int(match[1]) if match else None
    counts = {key: count(label) for key, label in [('routable','routable nets'),('routed','fully routed nets'),('errors','nets with routing errors')]}
    counts['explicit_gaps'] = count('nets with explicit gaps') or 0
    counts['complete'] = counts['explicit_gaps'] == 0 and counts['routable'] is not None and counts['routable'] > 0 and counts['routed'] == counts['routable'] and counts['errors'] == 0
    return counts

def metrics(path):
    return dict(line.split('\t', 1) for line in read(path).splitlines()[1:] if '\t' in line)

def resource(text, label):
    match = re.search(r'^\|\s*'+re.escape(label)+r'\s*\|\s*([\d.]+)', text, re.M)
    return float(match[1]) if match else None

def inspect(name, run):
    folder = ROOT/'reports'/run
    r = route(read(folder/'route_status.rpt'))
    rr = route(read(folder/'reopen/route_status.rpt'))
    m, rm = metrics(folder/'metrics.tsv'), metrics(folder/'reopen/metrics.tsv')
    checks = {
        'explicit_route_flags': all(metrics(folder/'route_diagnostic/route_flags.tsv').get(k) == v for k,v in {'ROUTED_FULLY':'1','ERRORS_IN_ROUTES':'0','GAPS':'0','PARTIAL':'0','UNROUTED':'0','CONFLICTS':'0'}.items()),
        'audit_exit_zero': read(folder/'route_diagnostic/audit_exit_code').strip() == '0',
        'audit_dcp_unchanged': bool(read(folder/'route_diagnostic/checkpoint_before.sha256')) and read(folder/'route_diagnostic/checkpoint_before.sha256') == read(folder/'route_diagnostic/checkpoint_after.sha256'),
        'implementation_exit_zero': read(folder/'exit_code').strip() == '0',
        'route_complete': r['complete'],
        'reopen_exit_zero': read(folder/'reopen/exit_code').strip() == '0',
        'reopen_marker': bool(read(folder/'reopen/reopened.txt').strip()),
        'reopen_route_complete': rr['complete'],
        'reopen_route_counts_match': r['routable'] is not None and r == rr,
        'no_blackboxes': m.get('blackboxes') == rm.get('blackboxes') == '0',
        'no_drc_errors': m.get('drc_errors') == rm.get('drc_errors') == '0',
        'no_drc_critical_warnings': m.get('drc_critical_warnings') == rm.get('drc_critical_warnings') == '0',
        'timing_reproduced': all(key in m and m.get(key) == rm.get(key) for key in ['max_slack_ns','min_slack_ns']),
    }
    try:
        setup, hold = float(m['max_slack_ns']), float(m['min_slack_ns'])
        timing = 'PASS' if setup >= 0 and hold >= 0 else 'FAIL'
    except (KeyError, ValueError):
        setup = hold = None
        timing = 'PENDING'
    util = read(folder/'utilization.rpt')
    resources = {label: resource(util,label) for label in ['CLB LUTs','CLB Registers','Block RAM Tile','DSPs','URAM','Total SLLs Used']}
    log = read(folder/'run.log')
    wall = re.search(r'Elapsed \(wall clock\) time \(h:mm:ss or m:ss\): ([^\n]+)', log)
    rss = re.search(r'Maximum resident set size \(kbytes\): (\d+)', log)
    result = dict(case=name, run=run, server_path=SERVER+'/runs/'+run,
                  checkpoint=SERVER+'/runs/'+run+'/routed.dcp',
                  physical_status='VERIFIED' if all(checks.values()) else 'PENDING_OR_FAILED',
                  timing_status=timing, wns_ns=setup, whs_ns=hold,
                  checks=checks, route=r, metrics=m, resources=resources,
                  wall_time=wall[1] if wall else None, peak_rss_mib=int(rss[1])/1024 if rss else None,
                  route_flags=metrics(folder/'route_diagnostic/route_flags.tsv'),
                  internal_timing=metrics(folder/'route_diagnostic/internal_timing.tsv'),
                  region_audit=read(folder/'route_diagnostic/audit_summary.txt'),
                  hls_provenance='Vitis HLS 2023.2 regenerated; upstream C simulation passed' if name=='VTA' else 'Upstream 2019.1 exported HDL; 2023.2 source HLS failed at missing systemc.h')
    folder.mkdir(parents=True,exist_ok=True)
    (folder/'validation.json').write_text(json.dumps(result,indent=2)+'\n')
    (folder/'summary.md').write_text(f"# {name} U250 baseline\n\nPhysical: {result['physical_status']}. Timing: {timing}, WNS/WHS {setup}/{hold} ns at 10ns.\n\nServer: `{result['server_path']}`. DCP remains server-only at `{result['checkpoint']}`.\n\n{result['hls_provenance']}. OOC core only; board inference not verified. See validation.json for explicit checks.\n")
    return result

if __name__ == '__main__':
    results = [inspect(name,run) for name,run in CASES.items()]
    (ROOT/'results.json').write_text(json.dumps(results,indent=2)+'\n')
    lines=['# Benchmark results','', '| Case | Physical | Timing | WNS (ns) | WHS (ns) | Run |', '|---|---|---|---:|---:|---|']
    for r in results:
        lines.append(f"| {r['case']} | {r['physical_status']} | {r['timing_status']} | {r['wns_ns']} | {r['whs_ns']} | [{r['run']}]({r['run']}/summary.md) |")
    lines += ['', 'Physical and timing acceptance are distinct. All DCPs remain on eda070. CNNA uses unchanged upstream exported HDL; it has not been regenerated by HLS 2023.2. Both cases are OOC cores; no board inference result is claimed.', '']
    (ROOT/'reports/index.md').write_text('\n'.join(lines))
    print(json.dumps([{k:r[k] for k in ['case','physical_status','timing_status','wns_ns','whs_ns']} for r in results],indent=2))
