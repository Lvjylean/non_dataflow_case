"""Accept only independently verified, timing-closed two-SLR platform builds."""
import csv,json,re,sys
from pathlib import Path
from summarize import route,metrics,read

root=Path(__file__).resolve().parents[1]
run=root/'reports'/sys.argv[1]
configuration=root/'reports'/sys.argv[2] if len(sys.argv)>2 else run
physical=run/'physical'; reopened=physical/'reopen'
resource_audit=root/'reports'/sys.argv[3] if len(sys.argv)>3 else reopened
def regions(path):
    if not path.is_file():return []
    rows=list(csv.DictReader(path.open(),delimiter='\t'))
    return sorted([{k:r[k] for k in ['kernel','slr','primitive_count']} for r in rows],key=lambda r:(r['kernel'],r['slr']))
def native_resources(folder):
    result={}
    for report in folder.glob('*kernel_*_utilization.rpt'):
        values={}; header=False
        for line in report.read_text().splitlines():
            fields=[v.strip() for v in line.split('|')][1:-1]
            if len(fields)==9 and fields[1:5]==['SLR0','SLR1','SLR2','SLR3']:
                header=True
            elif header and len(fields)==9 and fields[0] in ['CLB LUTs','CLB Registers','Block RAM Tile','DSPs','URAM']:
                values[fields[0]]=[float(v) for v in fields[1:5]]
        if len(values)==5:result[report.name]=values
    return result
native=native_resources(physical)
rows=regions(physical/'accelerator_regions.tsv')
slrs={r['slr'] for r in rows if int(r['primitive_count'])>0}
dsp_slrs={f'SLR{i}' for resource in native.values() for i,count in enumerate(resource['DSPs']) if count>0}
kernels={r['kernel'] for r in rows}
expected=6 if run.name.startswith('cnna6') else 1
def timing_overview(folder):
    lines=read(folder/'timing_summary.rpt').splitlines()
    for i,line in enumerate(lines):
        if 'WNS(ns)' in line and 'WPWS(ns)' in line:
            for candidate in lines[i+1:i+5]:
                fields=candidate.split()
                if len(fields)==12:
                    try:
                        keys=['wns_ns','tns_ns','setup_failing_endpoints','setup_total_endpoints','whs_ns','ths_ns','hold_failing_endpoints','hold_total_endpoints','wpws_ns','tpws_ns','pulse_failing_endpoints','pulse_total_endpoints']
                        return {key:float(value) if key.endswith('_ns') else int(value) for key,value in zip(keys,fields)}
                    except ValueError:pass
    return {}
m=metrics(physical/'metrics.tsv'); rm=metrics(reopened/'metrics.tsv')
flags={'ROUTED_FULLY':'1','ERRORS_IN_ROUTES':'0','GAPS':'0','PARTIAL':'0','UNROUTED':'0','CONFLICTS':'0'}
audit=json.loads(read(run/'interface_audit.json') or '{}')
checks={
 'artifact_generation_exit_zero':read(configuration/'exit_code').strip()=='0',
 'configuration_hash_present':bool(re.match(r'^[0-9a-f]{64}  ',read(configuration/'configuration.sha256'))),
 'configuration_package_matches':bool(read(run/'package_input.sha256')) and read(run/'package_input.sha256')==read(configuration/'package_input.sha256'),
 'interface_audit_pass':audit.get('status')=='PASS' and audit.get('axi_address_width')==64,
 'reopen_exit_zero':read(reopened/'exit_code').strip()=='0',
 'reopen_marker':bool(read(reopened/'reopened.txt')),
 'dcp_unchanged':bool(read(reopened/'checkpoint_before.sha256')) and read(reopened/'checkpoint_before.sha256')==read(reopened/'checkpoint_after.sha256'),
 'exactly_two_accelerator_slrs':slrs=={'SLR2','SLR3'},
 'compute_dsp_in_both_slrs':dsp_slrs=={'SLR2','SLR3'},
 'expected_engine_count':len(kernels)==expected,
 'native_slr_resources_reproduced':len(native)==expected and native==native_resources(resource_audit),
 'region_counts_reproduced':bool(rows) and rows==regions(reopened/'accelerator_regions.tsv'),
 'route_counts_reproduced':route(read(physical/'route_status.rpt'))==route(read(reopened/'route_status.rpt')),
 'timing_reproduced':all(k in m and m[k]==rm.get(k) for k in ['max_slack_ns','min_slack_ns']),
}
for label,folder in [('root',physical),('reopen',reopened)]:
    checks[label+'_route_complete']=route(read(folder/'route_status.rpt'))['complete']
    checks[label+'_route_flags']=all(metrics(folder/'route_flags.tsv').get(k)==v for k,v in flags.items())
    checks[label+'_clean_drc_and_no_blackboxes']=all(metrics(folder/'metrics.tsv').get(k)=='0' for k in ['drc_errors','drc_critical_warnings','blackboxes'])
try: timing=float(m['max_slack_ns'])>=0 and float(m['min_slack_ns'])>=0
except (KeyError,ValueError):timing=False
checks['full_timing_closed']=timing
timing_summary=timing_overview(physical); reopened_summary=timing_overview(reopened)
wpws=timing_summary.get('wpws_ns'); rwpws=reopened_summary.get('wpws_ns')
checks['pulse_width_pass_and_reproduced']=wpws is not None and wpws>=0 and wpws==rwpws
checks['full_timing_summary_reproduced']=bool(timing_summary) and timing_summary==reopened_summary
checks['detailed_cdc_available']=bool(read(resource_audit/'cdc_paths.rpt'))
checks['cdc_no_unreviewed_critical_paths']=checks['detailed_cdc_available'] and not re.search(r'^\s*\d+\s+CDC-\d+\s+Critical\b',read(resource_audit/'cdc_paths.rpt'),re.M)
if resource_audit!=reopened:
    checks['additional_resource_audit_exit_zero']=read(resource_audit/'exit_code').strip()=='0'
    before=read(resource_audit/'checkpoint_before.sha256')
    checks['additional_resource_audit_same_unchanged_dcp']=bool(before) and before==read(resource_audit/'checkpoint_after.sha256') and before==read(run/'checkpoint_before.sha256')
if configuration!=run:
    checks['container_metadata_pass']=json.loads(read(configuration/'container_metadata_validation.json') or '{}').get('status')=='PASS'
    checks['recovery_first_audit_exit_zero']=read(physical/'exit_code').strip()=='0'
    checks['recovery_source_consistent']=bool(read(run/'recovery_source.tsv')) and read(run/'recovery_source.tsv')==read(configuration/'recovery_source.tsv')
    checks['container_payload_matches']=read(configuration/'container_validation.tsv').strip()=='container_bitstream_matches_source\t1'
    checks['container_payload_from_this_recovery']=f'/runs/{run.name}/build/link/int/partial.bit' in read(configuration/'packaging_inputs.sha256')
    checks['source_checkpoint_unchanged']=bool(read(run/'checkpoint_before.sha256')) and read(run/'checkpoint_before.sha256')==read(run/'checkpoint_after.sha256')
coverage={}
for label,folder in [('root',physical),('reopen',reopened)]:
    counts={key:int(value) for key,value in re.findall(r'checking (\w+) \((\d+)\)',read(folder/'timing_summary.rpt'))}
    required=['no_clock','constant_clock','unconstrained_internal_endpoints','no_input_delay','no_output_delay','multiple_clock','generated_clocks','loops','partial_input_delay','partial_output_delay','latch_loops']
    coverage[label]=counts
    checks[label+'_timing_coverage_clean']=all(counts.get(key)==0 for key in required)
    methodology=read(folder/'methodology.rpt')
    checks[label+'_methodology_no_unreviewed_warnings']=bool(methodology) and not re.search(r'^\|[^\n]*\|\s*(?:Critical Warning|Warning)\s*\|',methodology,re.M)
    checks[label+'_verbose_coverage_and_cdc_present']=bool(read(folder/'check_timing.rpt')) and bool(read(folder/'cdc.rpt'))
review_checks={key for key in checks if key.endswith(('_timing_coverage_clean','_methodology_no_unreviewed_warnings')) or key=='cdc_no_unreviewed_critical_paths'}
status='VERIFIED' if all(checks.values()) else ('REVIEW_REQUIRED' if all(value for key,value in checks.items() if key not in review_checks) else 'PENDING_OR_FAILED')
result={'run':run.name,'configuration_run':configuration.name,'resource_audit':str(resource_audit.relative_to(root/'reports')),'status':status,'checks':checks,'metrics':m,'timing_summary':timing_summary,'timing_coverage':coverage,'accelerator_regions':rows,'native_slr_resources':native,'note':'Full U250 platform; accelerator hierarchy counted separately. Native utilization tables are authoritative; legacy REF_NAME DSP/BRAM leaf counters are ignored. Coverage/methodology findings require documented review; positive slack alone cannot pass. No board execution validation.'}
run.mkdir(parents=True,exist_ok=True)
(run/'platform_validation.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
