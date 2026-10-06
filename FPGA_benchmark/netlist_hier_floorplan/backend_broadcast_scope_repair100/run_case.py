#!/usr/bin/env python3
"""Run a fresh post-opt backend experiment with streamed stages and exact ECO checks."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import traceback
from collections import Counter


def validate_floorplan(folder, checkpoint_hash, fixture=False):
    manifest_path = folder/'manifest.json'
    if not manifest_path.is_file():
        if fixture:
            return dict(module_count=None, fixture=True)
        raise ValueError('A checkpoint-bound floorplan manifest is required')
    manifest = json.loads(manifest_path.read_text())
    if manifest.get('status') != 'PASS' or manifest.get('input_sha256') != checkpoint_hash:
        raise ValueError('Floorplan is unverified or belongs to a different checkpoint')
    required = {'regions.tcl', 'membership.tsv', 'export/modules.json'}
    if not required.issubset(manifest.get('files', {})):
        raise ValueError('Floorplan manifest omits required inputs')
    for name, expected in manifest['files'].items():
        candidate = (folder/name).resolve()
        if folder.resolve() not in candidate.parents or sha(candidate) != expected:
            raise ValueError('Floorplan manifest mismatch: '+name)
    metadata = json.loads((folder/'export/modules.json').read_text())
    modules = metadata['modules']
    identifiers = [m['module_id'] for m in modules]
    if len(set(identifiers)) != len(identifiers) or len(modules) != manifest['module_count']:
        raise ValueError('Module metadata count or identifiers are inconsistent')
    counts = Counter()
    with (folder/'membership.tsv').open() as stream:
        next(stream)
        for line in stream:
            fields = line.rstrip('\n').split('\t')
            if len(fields) != 4:
                raise ValueError('Expected four membership columns')
            counts[fields[1]] += 1
    if dict(counts) != manifest['counts']:
        raise ValueError('Membership counts differ from the manifest')
    for module in modules:
        if counts[module['module_id']] != module['cells']:
            raise ValueError('Module member count mismatch: '+module['module_id'])
    return dict(module_count=len(modules), counts=dict(counts), metadata=metadata)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(8388608), b''):
            h.update(block)
    return h.hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temp.replace(path)


def source_hashes(source):
    """The frozen source set, not merely the files mentioned by old evidence."""
    return {str(p.relative_to(source)): sha(p) for p in source.rglob('*')
            if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc'}


def validate_locality_admission(validation, source):
    """Require this exact source snapshot's new implementation/reopen proof."""
    evidence = validation.get('native_locality_evidence', {})
    if validation.get('status') != 'PASS' or validation.get('native_broadcast_locality_pass') is not True:
        raise ValueError('Broadcast locality requires new native integration evidence')
    if (not isinstance(evidence, dict) or evidence.get('status') != 'PASS' or
        evidence.get('implementation_pass') is not True or
        evidence.get('independent_reopen_pass') is not True):
        raise ValueError('Broadcast locality requires native implementation and independent reopen')
    hashes = validation.get('source_hashes', {})
    if not hashes or evidence.get('source_hashes') != hashes:
        raise ValueError('Native locality evidence is not bound to the validated source hashes')
    if hashes != source_hashes(source):
        raise ValueError('Native locality evidence does not match the complete current source snapshot')


def locality_environment(env, enabled):
    """The explicit CLI switch controls both child and recovery environments."""
    if enabled:
        env['BL_LOCALITY'] = '1'
        os.environ['BL_LOCALITY'] = '1'
    else:
        env.pop('BL_LOCALITY', None)
        os.environ.pop('BL_LOCALITY', None)


def seed_base_closure(source):
    """Resolve the actual seed/base source closure without executing Tcl.

    Source expressions are deliberately a small audited grammar.  A new dynamic
    expression cannot silently escape the dependency check: it fails closed.
    Floorplan source is covered by input_manifest; SLL replay is prohibited.
    """
    source = source.resolve()
    fixed = {'chain.tcl', 'clock.tcl', 'checkpoint_io.tcl',
             'spatial_policy.tcl', 'sll_balance.tcl'}
    closure = {str(p.relative_to(source)) for p in (source/'code/base').rglob('*')
               if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc'}
    queue = list(sorted(fixed))
    scanned = set()
    while queue:
        name = queue.pop()
        if name in scanned:
            continue
        scanned.add(name); closure.add(name)
        path = source/name
        if not path.is_file():
            raise ValueError('Seed/base dependency is missing: '+name)
        for match in re.finditer(r'^\s*source\s+(.+?)\s*$', path.read_text(), re.M):
            expression = match[1]
            if ((name == 'code/base/balanced_implementation/adapter.tcl' and expression == '$input/regions.tcl') or
                (name == 'sll_balance.tcl' and expression == '$plan')):
                continue
            if name == 'chain.tcl' and expression == '$compilefast_code/code/regional/run.tcl':
                continue  # This command starts the later generic stage.
            if expression.startswith('$compilefast_code/'):
                dependency = source/expression[len('$compilefast_code/'):]
            elif expression.startswith('$here/'):
                dependency = path.parent/expression[len('$here/'):]
            elif expression.startswith('[file join [file dirname [info script]] ') and expression.endswith(']'):
                parts = expression[len('[file join [file dirname [info script]] '):-1].split()
                dependency = path.parent.joinpath(*parts)
            elif expression.startswith('[file join $here ') and expression.endswith(']'):
                dependency = path.parent.joinpath(*expression[len('[file join $here '):-1].split())
            elif expression.startswith('[file dirname [info script]]/'):
                dependency = path.parent/expression[len('[file dirname [info script]]/'):]
            else:
                raise ValueError('Unresolved seed/base source expression: '+name+': '+expression)
            # Do not interpret variables, substitutions, or shell-like quoting.
            if any(ch in str(dependency) for ch in '$[]{};\n\r'):
                raise ValueError('Dynamic seed/base source dependency: '+name)
            dependency = dependency.resolve()
            try:
                relative = str(dependency.relative_to(source))
            except ValueError:
                raise ValueError('Seed/base dependency escapes source tree: '+name)
            queue.append(relative)
    return sorted(closure)


def verify_seed_base_closure(previous, source):
    manifest = json.loads((previous/'source_manifest.json').read_text())
    closure = seed_base_closure(source)
    old_base = {name for name in manifest if name.startswith('code/base/')}
    new_base = {name for name in closure if name.startswith('code/base/')}
    if old_base != new_base:
        raise ValueError('Seed/base file set changed')
    for name in closure:
        if name not in manifest or sha(source/name) != manifest[name]:
            raise ValueError('Seed/base source dependency changed: '+name)
    return {name: manifest[name] for name in closure}


def admit_base_resume(previous, expected, root, source, args):
    """Recover only a discovery failure, before any generic ECO was applied."""
    previous = previous.resolve()
    prior = json.loads((previous/'status.json').read_text())
    loc = json.loads((previous/'location.json').read_text())
    if prior.get('status') != 'STOPPED_WITH_EVIDENCE' or prior.get('active_pid') is not None:
        raise ValueError('Resume requires a stopped previous attempt')
    impl = previous/'generic/implementation'
    if (impl/'phase.txt').read_text().split()[-1] != 'discovery' or (impl/'after_edit').exists():
        raise ValueError('Only pre-edit discovery failure may resume from base')
    if (loc['post_opt_sha256'] != args.expected_sha256 or
        float(loc['clock_period_ns']) != args.period or
        loc['fanout_required_lt'] != 100 or (previous/'sll_input.json').exists()):
        raise ValueError('Resume conditions differ or SLL recovery is unsupported')
    if json.loads((previous/'input_manifest.json').read_text()) != json.loads((root/'input_manifest.json').read_text()):
        raise ValueError('Resume floorplan differs')
    manifest = json.loads((previous/'source_manifest.json').read_text())
    if getattr(args, 'broadcast_locality', False):
        verify_seed_base_closure(previous, source)
        if not getattr(args, 'fixture', False):
            validate_locality_admission(json.loads((root/'tests/local_results.json').read_text()), source)
    else:
        for name, value in manifest.items():
            if name.startswith('code/base/') or name in {
                'chain.tcl','clock.tcl','checkpoint_io.tcl','spatial_policy.tcl','sll_balance.tcl'}:
                if sha(source/name) != value:
                    raise ValueError('Seed/base source changed: '+name)
    checkpoint = previous/'base/pre_route.dcp'
    if not (previous/'base/complete.txt').is_file() or sha(checkpoint) != expected:
        raise ValueError('Completed base checkpoint/hash not verified')
    for stage in ['seed','base']:
        (root/stage).symlink_to(previous/stage, target_is_directory=True)
    evidence = dict(previous=str(previous),checkpoint=str(checkpoint),sha256=expected,
                    prior_compile_seconds=prior['compile_seconds'],
                    reused_stages=['seed','base'],failure_phase='discovery')
    write(root/'resume_base.json',evidence)
    return evidence


def admit_base_replay(previous, expected, root, source, args):
    """Start a new experiment from a completed, unchanged second placement."""
    previous = previous.resolve()
    prior = json.loads((previous/'status.json').read_text())
    loc = json.loads((previous/'location.json').read_text())
    scope_repair = getattr(args, 'scope_repair_plan', None)
    if scope_repair:
        impl = previous/'generic/implementation'
        error = (impl/'error.txt').read_text()
        if (prior.get('status') != 'STOPPED_WITH_EVIDENCE' or prior.get('active_pid') is not None or
                (impl/'phase.txt').read_text().split()[-1] != 'post_place_validation' or
                not any(x in error for x in ('Replica outside target SLR:', 'Replica SLR scope audit failed (')) or (impl/'post_route.dcp').exists()):
            raise ValueError('Scope repair requires the specific stopped pre-route placement scope failure')
        if scope_repair.resolve() != (impl/'plan.tcl').resolve() or sha(scope_repair) != args.scope_repair_plan_sha256:
            raise ValueError('Scope repair plan identity changed')
        # Read only serialized Tcl lists; never evaluate an unreviewed plan.
        sanitizer = Path(__file__).resolve().parent/'validate_saved_plan.tcl'
        subprocess.run(['tclsh',str(sanitizer),str(scope_repair)],check=True,capture_output=True,text=True)
        shutil.copyfile(scope_repair,root/'scope_repair_plan.tcl')
        placed = getattr(args, 'scope_repair_checkpoint', None)
        if placed:
            if (placed.resolve() != (impl/'post_place/failed_scope.dcp').resolve() or
                    sha(placed) != args.scope_repair_checkpoint_sha256 or
                    not (impl/'post_place/replica_scope_all.tsv').is_file()):
                raise ValueError('Preserved placement scope checkpoint identity changed')
            rows = (impl/'post_place/replica_scope_all.tsv').read_text().splitlines()
            if not any(row.endswith('\tFAIL') for row in rows[1:]):
                raise ValueError('Preserved placement has no documented scope failures')
    elif prior.get('status') != 'COMPLETE_REVIEW_CRITERIA' or prior.get('active_pid') is not None:
        raise ValueError('Base replay requires a completed inactive experiment')
    if (loc['post_opt_sha256'] != args.expected_sha256 or
        float(loc['clock_period_ns']) != args.period or
        loc['fanout_required_lt'] != 100 or (previous/'sll_input.json').exists()):
        raise ValueError('Base replay conditions differ or contain SLL reservation')
    if json.loads((previous/'input_manifest.json').read_text()) != json.loads((root/'input_manifest.json').read_text()):
        raise ValueError('Base replay floorplan differs')
    closure = None
    if getattr(args, 'broadcast_locality', False):
        closure = verify_seed_base_closure(previous, source)
        if not getattr(args, 'fixture', False):
            validate_locality_admission(json.loads((root/'tests/local_results.json').read_text()), source)
    else:
        allowed_changes = {'run_case.py','report_result.py','validate_local.py',
                           'code/regional/joint_gate.py','code/regional/joint_input.py'}
        for name, value in json.loads((previous/'source_manifest.json').read_text()).items():
            if name not in allowed_changes and sha(source/name) != value:
                raise ValueError('Unexpected change to validated physical flow: '+name)
    checkpoint = previous/'base/pre_route.dcp'
    if not (previous/'base/complete.txt').is_file() or sha(checkpoint) != expected:
        raise ValueError('Completed base checkpoint/hash not verified')
    clock = re.search(r'^'+re.escape(args.clock_port)+r'\s+\{[^}]*\}\s+([\d.]+)',
                      (previous/'base/pre_route/timing_summary.rpt').read_text(),re.M)
    if clock is None or abs(float(clock[1])-args.period)>1e-6:
        raise ValueError('Saved second placement clock period differs')
    for stage in ['seed','base']:
        (root/stage).symlink_to(previous/stage,target_is_directory=True)
    evidence = dict(previous=str(previous),checkpoint=str(checkpoint),sha256=expected,
                    reused_stages=['seed','base'],scope='new_experiment_from_second_placement',
                    previous_total_seconds=prior['compile_seconds'],
                    previous_total_included_in_new_runtime=False)
    if closure is not None:
        evidence.update(seed_base_source_hashes=closure,
                        native_locality_revalidated=not getattr(args, 'fixture', False))
    if scope_repair:
        evidence.update(scope_repair=True, reused_plan_sha256=args.scope_repair_plan_sha256,
                        original_failed_seconds=prior['compile_seconds'],
                        reused_candidate_plan=True, original_third_placement_not_saved=not bool(getattr(args,'scope_repair_checkpoint',None)))
        if getattr(args,'scope_repair_checkpoint',None):
            evidence.update(placed_checkpoint=str(args.scope_repair_checkpoint),
                placed_sha256=args.scope_repair_checkpoint_sha256,
                scope='from_preserved_third_placement', original_third_placement_reused=True)
    write(root/'replay_base.json',evidence)
    return evidence


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--input', type=Path, required=True)
    ap.add_argument('--expected-sha256', required=True)
    ap.add_argument('--floorplan', type=Path, required=True)
    ap.add_argument('--period', type=float, required=True)
    ap.add_argument('--work-root', type=Path, required=True)
    ap.add_argument('--validation-json', type=Path, required=True)
    ap.add_argument('--case-name', default='FPGA backend')
    ap.add_argument('--clock-port', default='ap_clk')
    ap.add_argument('--reference-root', default='')
    ap.add_argument('--reference-seconds', type=float)
    ap.add_argument('--reference-period', type=float)
    ap.add_argument('--memory-required-gib', type=float, default=42)
    ap.add_argument('--joint-margin', type=float, default=.2)
    ap.add_argument('--joint-max-added', type=int, default=8192)
    ap.add_argument('--joint-per-endpoint', type=int, default=512)
    ap.add_argument('--timing-extraction', choices=['pin', 'reference'], default='pin',
                    help='Complete endpoint slack extraction; both use identical acceptance rules')
    ap.add_argument('--resume-base-root', type=Path, help='Stopped pre-edit attempt with completed seed/base')
    ap.add_argument('--resume-base-sha256', help='Expected SHA256 of its base/pre_route.dcp')
    ap.add_argument('--replay-base-root', type=Path, help='Completed experiment whose second placement is reused')
    ap.add_argument('--scope-repair-plan', type=Path, help='Validated saved plan for the specific stopped SLR scope failure')
    ap.add_argument('--scope-repair-plan-sha256')
    ap.add_argument('--scope-repair-checkpoint', type=Path, help='Preserved third-placement scope-failure checkpoint')
    ap.add_argument('--scope-repair-checkpoint-sha256')
    ap.add_argument('--replay-base-sha256', help='Expected SHA256 of the completed second placement checkpoint')
    ap.add_argument('--expected-joint-plan', type=Path, help='Require identical first-pass joint candidates before editing')
    ap.add_argument('--joint-wns-policy', choices=['nonworse','positive'], default='nonworse')
    ap.add_argument('--broadcast-locality', action='store_true',
                    help='Enable validated identity-tree broadcast and combinational locality planning')
    ap.add_argument('--vivado', default='/home/lduac/Software/Xilinx/Vivado/2023.2/bin/vivado')
    ap.add_argument('--sll-plan', type=Path, help='Validated temporary capacity reservation Tcl plan')
    ap.add_argument('--fixture', action='store_true', help=argparse.SUPPRESS)
    args = ap.parse_args()
    if args.period <= 0 or args.memory_required_gib < 0:
        ap.error('Period must be positive and memory budget nonnegative')
    if min(args.joint_margin,args.joint_max_added,args.joint_per_endpoint)<0:
        ap.error('Joint planning budgets must be nonnegative')
    if bool(args.resume_base_root) != bool(args.resume_base_sha256):
        ap.error('Both base resume root and checkpoint SHA256 are required')
    if args.resume_base_root and args.sll_plan:
        ap.error('SLL reservation recovery is not supported at this boundary')
    if bool(args.replay_base_root) != bool(args.replay_base_sha256):
        ap.error('Both replay root and checkpoint SHA256 are required')
    if args.replay_base_root and (args.resume_base_root or args.sll_plan):
        ap.error('Completed base replay cannot combine with failure recovery or SLL reservation')
    if args.expected_joint_plan and not args.replay_base_root:
        ap.error('Candidate identity check requires completed base replay')
    if args.scope_repair_plan and (not args.replay_base_root or not args.broadcast_locality or not args.scope_repair_plan_sha256):
        ap.error('Scope repair requires base replay, locality and a pinned plan hash')
    if bool(args.scope_repair_checkpoint) != bool(args.scope_repair_checkpoint_sha256) or (args.scope_repair_checkpoint and not args.scope_repair_plan):
        ap.error('Placed scope repair requires a pinned checkpoint and saved plan')
    root = args.work_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    with (root/'controller.lock').open('x') as stream:
        stream.write(str(os.getpid()))
    state = dict(status='PREPARING', start=time.time(), controller_pid=os.getpid(), stages=[])

    def update(**values):
        state.update(values, updated=time.time())
        write(root/'status.json', state)

    code = root/'flow'
    env = os.environ.copy()
    # Never accept an inherited cache or enable flag from an unrelated run.
    for cache_name in ('BL_STATIC_CACHE_ENABLED', 'BL_STATIC_CACHE_SOURCE'):
        env.pop(cache_name, None)
        os.environ.pop(cache_name, None)
    locality_environment(env, args.broadcast_locality)
    env.update(COMPILEFAST_PERIOD=str(args.period), EXPERIMENT_INPUT=str(root/'inputs'),
               COMPILEFAST_RUN_ROOT=str(root), COMPILEFAST_CLOCK_PORT=args.clock_port)
    env.update(JI_MARGIN=str(args.joint_margin),JI_MAX_ADDED=str(args.joint_max_added),JI_PER_ENDPOINT=str(args.joint_per_endpoint))
    env['JI_TIMING_MODE'] = args.timing_extraction
    env['JI_WNS_POLICY'] = args.joint_wns_policy
    env.pop('JI_EXCLUDE',None)
    env.pop('JI_EXPECTED_PLAN',None)
    if args.expected_joint_plan:
        env['JI_EXPECTED_PLAN'] = str(root/'expected_joint_plan.json')
    if args.sll_plan:
        env['COMPILEFAST_SLL_PLAN'] = str((root/'sll_plan.tcl').resolve())
    if args.fixture:
        env['COMPILEFAST_FIXTURE'] = '1'
    for name in ['JI_EXCLUDE','JI_EXPECTED_PLAN']:
        os.environ.pop(name,None)
    os.environ.update({k:v for k,v in env.items() if k.startswith(('COMPILEFAST_','JI_')) or k == 'EXPERIMENT_INPUT'})
    generic = None

    def launch(name, script, arguments):
        command = [args.vivado, '-mode', 'batch', '-source', str(script),
                   '-log', str(root/(name+'.log')), '-journal', str(root/(name+'.jou')),
                   '-tclargs', *map(str, arguments)]
        begin = time.time()
        with (root/(name+'_console.log')).open('x') as log:
            process = subprocess.Popen(command, cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT)
            update(status='RUNNING', stage=name, active_pid=process.pid)
            rc = process.wait()
        state['stages'].append(dict(name=name, returncode=rc, seconds=time.time()-begin,
                                    included_in_compile_time=True))
        update(active_pid=None)
        return rc

    try:
        if sha(args.input) != args.expected_sha256:
            raise ValueError('Post-opt input hash mismatch')
        validation = json.loads(args.validation_json.read_text())
        if validation.get('status') != 'PASS':
            raise ValueError('Validation did not pass')
        if not args.fixture and (not validation.get('native_integration_pass') or not validation.get('source_hashes')):
            raise ValueError('Production requires native integration evidence and frozen source hashes')
        if not args.fixture and (not validation.get('native_physical_eco_pass') or
                                 'physical_eco.tcl' not in validation.get('source_hashes', {})):
            raise ValueError('Production requires native changed-D legalization and reopened routing evidence')
        if not args.fixture and not validation.get('native_joint_input_pass'):
            raise ValueError('Production requires native complete-MUX joint planning, STA guard and independent reopen evidence')
        if not args.fixture and args.timing_extraction == 'pin' and not validation.get('native_fast_timing_equivalence_pass'):
            raise ValueError('Fast timing requires full endpoint equivalence and native integration evidence')
        if args.scope_repair_checkpoint:
            proof = validation.get('native_scope_repair_evidence', {})
            if (not validation.get('native_scope_repair_pass') or proof.get('status') != 'PASS' or
                    proof.get('source_hashes') != validation.get('source_hashes') or
                    proof.get('unrelated_geometry_preserved') is not True or
                    proof.get('reopened_scope_and_routing_pass') is not True):
                raise ValueError('Placed scope recovery requires native local-repair and reopen evidence')
        source = Path(__file__).resolve().parent
        # Cross-session static reuse is enabled only after native live-base vs
        # reopened-base equivalence has been bound to this exact source set.
        cache_proof = validation.get('native_static_discovery_cache_evidence', {})
        if args.broadcast_locality and validation.get('native_static_discovery_cache_pass') is True:
            if (cache_proof.get('status') != 'PASS' or
                    cache_proof.get('source_hashes') != validation.get('source_hashes') or
                    cache_proof.get('live_vs_reopened_static_equivalent') is not True or
                    cache_proof.get('retry_finish_equivalent') is not True):
                raise ValueError('Static discovery cache lacks native equivalence proof')
            env['BL_STATIC_CACHE_ENABLED'] = '1'
        if args.broadcast_locality and not args.fixture:
            validate_locality_admission(validation, source)
        for name, expected in validation.get('source_hashes', {}).items():
            if sha(source/name) != expected:
                raise ValueError('Validated source changed: '+name)
        shutil.copytree(source, code, ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        if args.sll_plan:
            if not args.fixture and not validation.get('native_sll_reservation_pass'):
                raise ValueError('SLL run requires native exact-channel and removal validation')
            shutil.copyfile(args.sll_plan,root/'sll_plan.tcl')
            write(root/'sll_input.json',dict(plan=str(args.sll_plan.resolve()),sha256=sha(args.sll_plan),
                  threshold=0.8,blocked_fraction=1/3,removed_before_full_route=True))
        shutil.copytree(args.floorplan, root/'inputs')
        floorplan_info = validate_floorplan(root/'inputs', args.expected_sha256, args.fixture)
        files = {str(p.relative_to(root/'inputs')):sha(p) for p in (root/'inputs').rglob('*') if p.is_file()}
        write(root/'input_manifest.json', dict(input_sha256=args.expected_sha256, files=files))
        write(root/'floorplan_validation.json', floorplan_info)
        write(root/'tests/local_results.json', validation)
        write(root/'source_manifest.json', {str(p.relative_to(code)):sha(p) for p in code.rglob('*') if p.is_file()})
        if args.expected_joint_plan:
            shutil.copyfile(args.expected_joint_plan,root/'expected_joint_plan.json')
        write(root/'location.json', dict(server='eda070', server_root=str(root), post_opt=str(args.input),
              case_name=args.case_name, clock_port=args.clock_port, module_count=floorplan_info['module_count'],
              post_opt_sha256=args.expected_sha256, floorplan_source=str(args.floorplan),
              clock_period_ns=args.period, reference_root=args.reference_root,
              reference_clock_ns=args.reference_period, reference_total_s=args.reference_seconds,
              threads=8, memory_required_gib=args.memory_required_gib,
              execution_profile='streamed_stages_boundary_rewire', full_route_count=1,
              fanout_required_lt=100, fanout_branch_target=96, native_cleanup_target=80,
              timing_extraction=args.timing_extraction, timing_guard_coverage='all_affected_endpoints',
              joint_wns_policy=args.joint_wns_policy, base_replay=bool(args.replay_base_root),
              broadcast_locality=args.broadcast_locality,
              compile_scope=('from_preserved_third_placement' if args.scope_repair_checkpoint else ('from_second_placement' if args.replay_base_root else 'complete_flow')),
              monitoring='on_user_request_only'))
        if args.replay_base_root:
            replay=admit_base_replay(args.replay_base_root,args.replay_base_sha256,root,code,args)
            state['stages'].append(dict(name='reused_seed_base',seconds=0,returncode=0,
                included_in_compile_time=False,reused=True,source=replay['previous']))
        if args.resume_base_root:
            resume = admit_base_resume(args.resume_base_root,args.resume_base_sha256,root,code,args)
            state['stages'].append(dict(name='preserved_prior_attempt_including_failure',
                seconds=resume['prior_compile_seconds'],returncode=1,included_in_compile_time=True,
                reused=True,source=resume['previous']))
        wait_start = time.time()
        while True:
            memory = Path('/proc/meminfo').read_text()
            available = int(re.search(r'^MemAvailable:\s+(\d+)',memory,re.M)[1])/1024**2
            write(root/'memory_admission.json', dict(available_gib=available, required_gib=args.memory_required_gib,time=time.time()))
            if available >= args.memory_required_gib:
                break
            update(status='WAITING_MEMORY', stage='before_chain', active_pid=None)
            time.sleep(30)
        update(admission_wait_s=time.time()-wait_start, compile_started=time.time())
        if args.replay_base_root:
            mode = 'scope_repair' if args.scope_repair_checkpoint else ('edit' if args.scope_repair_plan else 'run')
            saved_plan = root/'scope_repair_plan.tcl' if args.scope_repair_plan else ''
            rc = launch('generic_base_replay', code/'code/regional/run.tcl',
                        [args.scope_repair_checkpoint or root/'base/pre_route.dcp',root/'generic/implementation',mode,saved_plan,16,1000,'structure',1,16,96,2,2,50000,'run','fast'])
        elif args.resume_base_root:
            rc = launch('generic_recovery', code/'code/regional/run.tcl',
                        [root/'base/pre_route.dcp',root/'generic/implementation','run','',16,1000,'structure',1,16,96,2,2,50000,'run','fast'])
        else:
            rc = launch('chain', code/'chain.tcl', [root/'inputs',args.input,root])
        if rc == 77:
            # One bounded retry from the unedited, legally placed checkpoint.
            # No failed candidate's placement, certificate or routing is reused.
            impl = root/'generic/implementation'
            rejected = json.loads((impl/'joint_placed/reject_ids.json').read_text())
            if not rejected:
                raise RuntimeError('Timing rejection has no safe removable candidate group')
            archived = root/'generic/rejected_attempt0'
            impl.rename(archived)
            write(root/'joint_excluded.json', rejected)
            env['JI_EXCLUDE'] = str(root/'joint_excluded.json')
            if env.get('BL_STATIC_CACHE_ENABLED') == '1':
                env['BL_STATIC_CACHE_SOURCE'] = str(archived/'locality')
            env.pop('JI_EXPECTED_PLAN',None)  # A bounded retry intentionally excludes rejected candidates.
            os.environ['JI_EXCLUDE'] = env['JI_EXCLUDE']
            os.environ.pop('JI_EXPECTED_PLAN',None)
            rc = launch('joint_retry1', code/'code/regional/run.tcl',
                        [root/'base/pre_route.dcp',impl,'run','',16,1000,'structure',1,16,96,2,2,50000,'run','fast'])
            if rc == 77:
                raise RuntimeError('Bounded joint timing retry rejected before routing; preserved both attempts')
        # Use the proven bounded recovery driver only for its typed handoff.
        spec = importlib.util.spec_from_file_location('regional_runner',code/'code/regional/run_case.py')
        generic = importlib.util.module_from_spec(spec); spec.loader.exec_module(generic)
        gstate = dict(status='RUNNING',stages=[],start=state['compile_started'],execution_profile='fast')
        opts = argparse.Namespace(vivado=args.vivado,min_fanout=16,path_limit=1000,selection='structure',
                    regional='on',regional_min_fanout=16,regional_branch_limit=96,region_width=2,
                    region_height=2,regional_max_luts=50000,legacy_eco='run',execution_profile='fast')
        impl = root/'generic/implementation'
        if rc == 75:
            boundary = (impl/'recovery/pending.txt').read_text().strip()
            if boundary not in {'post_place','post_route'}:
                raise RuntimeError('Invalid chain recovery boundary')
            checkpoint = impl/'recovery'/f'{boundary}.dcp'
            gstate['recoveries'] = [dict(boundary=boundary,checkpoint=str(checkpoint),
                    checkpoint_sha256=sha(checkpoint),plan_sha256=sha(impl/'plan.tcl'),
                    acceptance='Required in fresh Vivado process')]
            begin = time.time()
            generic.run_stage(opts,code/'code/regional',root/'generic',gstate,'implementation',
                              checkpoint,impl,'_resume_'+boundary,impl/'plan.tcl')
            state['stages'].append(dict(name='typed_recovery',seconds=time.time()-begin,returncode=0,included_in_compile_time=True))
        elif rc:
            raise RuntimeError(f'Chained implementation returned {rc}')
        if not (impl/'complete.txt').is_file():
            raise RuntimeError('Missing complete implementation')
        begin = time.time()
        update(stage='independent_reopen')
        generic.run_stage(opts,code/'code/regional',root/'generic',gstate,'reopen',
                          impl/'post_route.dcp',root/'generic/reopened','reopen',impl/'plan.tcl')
        state['stages'].append(dict(name='independent_reopen',seconds=time.time()-begin,returncode=0,included_in_compile_time=True))
        after = generic.timing(impl/'post_route/timing_summary.rpt')
        reopened = generic.timing(root/'generic/reopened/timing_summary.rpt')
        if after != reopened:
            raise RuntimeError('Independent reopened timing differs')
        write(root/'generic/comparison.json',dict(post_route=after,reopened=reopened,
              dcp=str(impl/'post_route.dcp'),dcp_sha256=sha(impl/'post_route.dcp')))
        gstate.update(status='COMPLETE',end=time.time())
        write(root/'generic/status.json',gstate)
        update(status='COMPLETE_REVIEW_CRITERIA',stage='IMPLEMENTED_REOPENED_AUDITED')
    except Exception as exc:
        update(status='STOPPED_WITH_EVIDENCE',error=repr(exc),traceback=traceback.format_exc())
    finally:
        update(end=time.time(),active_pid=None,
               compile_seconds=sum(x['seconds'] for x in state['stages'] if x['included_in_compile_time']),
               input_unchanged=sha(args.input)==args.expected_sha256)
        if (root/'location.json').exists():
            with (root/'report_console.log').open('w') as log:
                report=subprocess.run([sys.executable,str(code/'report_result.py')],cwd=root,env=env,stdout=log,stderr=subprocess.STDOUT)
            update(report_returncode=report.returncode,report_ready=report.returncode==0)
    return 1 if state['status']=='STOPPED_WITH_EVIDENCE' or state.get('report_returncode',1) else 0


if __name__ == '__main__':
    sys.exit(main())
