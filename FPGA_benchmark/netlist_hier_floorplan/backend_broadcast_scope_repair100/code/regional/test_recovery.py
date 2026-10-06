"""Exercise the real Tcl entry and Python handoff with explicit Vivado API mocks."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import run_case


CORE = r'''
namespace eval sb {}
proc event {name} {
    set f [open $::env(RF_TEST_EVENTS) a]; puts $f $name; close $f
}
proc sb::spatial_cache {} {}
proc sb::scan {args} {return [dict create no_op 0 data {}]}
proc sb::save {plan path} {
    set f [open $path w]; puts $f [list set sb_plan $plan]; close $f
}
proc sb::apply {plan out} {event apply; return $plan}
proc sb::reports {plan out routed} {file mkdir $out}
proc sb::verify {plan out placed} {
    event "sb_verify:$::mode:[file tail $out]"
    if {[string match _resume_* $::mode] && $::env(RF_TEST_REOPEN_FAIL) eq "structure"} {
        error "Connectivity mismatch in reopened checkpoint"
    }
}
'''

REGIONAL = r'''
namespace eval rf {}
proc rf::configure {options} {set ::rf::config $options}
proc rf::legacy_exclusions {plan} {return {}}
proc rf::discover {args} {return [dict create lut_added 1 roots {}]}
proc rf::validate_edit_scope {args} {}
proc rf::apply {plan out} {event regional_apply; return $plan}
proc rf::region_constraints {args} {event constraints}
proc rf::reports {args} {}
proc rf::verify {plan out placed} {
    event "rf_verify:$::mode:[file tail $out]"
    if {[string match _resume_* $::mode] && $::env(RF_TEST_REOPEN_FAIL) eq "protection"} {
        error "Original protection changed on reopened checkpoint"
    }
}
proc rf::restore_native_lut_protection {plan out} {
    set boundary [string range [file tail $out] 0 end-11]
    event "restore:$::mode:$boundary"
    if {$::env(RF_TEST_OTHER_ERROR) eq $boundary} {error "Unrecognized protection drift"}
    if {$boundary in $::env(RF_TEST_STICKY)} {
        return -code error -errorcode {RF NATIVE_LUT_PROTECTION_STICKY} "Native property stayed set"
    }
    return 0
}
'''

BOOTSTRAP = r'''
proc set_param {args} {}
proc open_checkpoint {path} {}
proc close_design {} {}
proc place_design {args} {event place}
proc update_clock_routing {} {event clock_route}
proc report_timing_summary {args} {event timing}
proc report_route_status {args} {event route_status}
proc route_design {} {event route}
proc write_checkpoint {path} {
    event "checkpoint:[file tail $path]"
    if {[file exists $path]} {error "Checkpoint overwrite"}
    set f [open $path w]; puts $f diagnostic; close $f
}
proc write_xdc {path} {set f [open $path w]; close $f}
source [file join [file dirname [info script]] run.tcl]
'''


class RecoveryIntegration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.code = self.root / 'code'
        self.code.mkdir()
        for name in ['run.tcl', 'recovery.tcl', 'execution.tcl']:
            shutil.copyfile(Path(__file__).parent / name, self.code / name)
        for name, data in [('core.tcl', CORE), ('regional.tcl', REGIONAL),
                           ('bootstrap.tcl', BOOTSTRAP)]:
            (self.code / name).write_text(data)
        # Physical audit hooks are integration-tested in the native fixture.
        # This harness isolates the real recovery state machine with API mocks.
        entry = self.code / 'run.tcl'
        script = entry.read_text()
        script = '\n'.join(line for line in script.splitlines()
                           if 'control/audit_active.tcl' not in line
                           and 'control/final_fanout.tcl' not in line
                           and 'experiment_final_fanout $out' not in line)
        entry.write_text(script)
        self.input = self.root / 'input.dcp'
        self.input.write_text('original')
        self.out = self.root / 'implementation'
        self.events = self.root / 'events.txt'
        self.state = {'stages': []}
        self.args = SimpleNamespace(vivado='mock-vivado', min_fanout=16, path_limit=1000,
            selection='structure', regional='on', regional_min_fanout=16,
            regional_branch_limit=96, region_width=2, region_height=2,
            regional_max_luts=50000, legacy_eco='run', execution_profile='reference')

    def execute(self, sticky='', other='', reopened='', mode='run', stage='implementation'):
        native_run = subprocess.run
        env = dict(os.environ, RF_TEST_EVENTS=str(self.events), RF_TEST_STICKY=sticky,
                   RF_TEST_OTHER_ERROR=other, RF_TEST_REOPEN_FAIL=reopened)

        def launch(command, **kwargs):
            argv = command[command.index('-tclargs') + 1:]
            return native_run(['tclsh', str(self.code / 'bootstrap.tcl'), *argv],
                              env=env, **kwargs)

        plan = None
        if mode in {'place', 'route', 'edit', 'reopen'}:
            plan = self.root / 'input_plan.tcl'
            plan.write_text('set sb_plan {no_op 0 data {} regional {lut_added 1 roots {}}}\n')
        with patch.object(run_case.subprocess, 'run', side_effect=launch):
            run_case.run_stage(self.args, self.code, self.root, self.state, stage,
                              self.input, self.out, mode, plan)

    def recorded(self):
        return self.events.read_text().splitlines() if self.events.exists() else []

    def test_normal_path_preserves_single_place_route(self):
        self.execute()
        self.assertEqual(self.recorded().count('place'), 1)
        self.assertEqual(self.recorded().count('route'), 1)
        self.assertEqual(len(self.state['stages']), 1)

    def test_fast_reuses_accepted_checkpoints(self):
        self.args.execution_profile = 'fast'
        self.execute(sticky='post_place post_route')
        checkpoints = [x for x in self.recorded() if x.startswith('checkpoint:')]
        self.assertEqual(checkpoints.count('checkpoint:post_place.dcp'), 1)
        self.assertEqual(checkpoints.count('checkpoint:post_route.dcp'), 1)
        self.assertEqual(len(self.state['checkpoint_publications']), 2)
        for boundary in ['post_place', 'post_route']:
            self.assertEqual((self.out / f'{boundary}.dcp').read_bytes(),
                             (self.out / 'recovery' / f'{boundary}.dcp').read_bytes())
        self.assertEqual(self.recorded().count('place'), 1)
        self.assertEqual(self.recorded().count('route'), 1)

    def test_published_checkpoint_hash_mismatch_is_fatal(self):
        self.args.execution_profile = 'fast'
        self.execute(sticky='post_place')
        self.state['checkpoint_publications'] = []
        (self.out / 'post_place.dcp').write_text('changed bytes')
        with self.assertRaisesRegex(ValueError, 'differs from recovery'):
            run_case.verify_publications(self.out, self.state)

    def test_publication_without_acceptance_is_fatal(self):
        self.args.execution_profile = 'fast'
        self.execute(sticky='post_place')
        self.state['checkpoint_publications'] = []
        self.state['recoveries'][0]['acceptance'] = 'Required'
        with self.assertRaisesRegex(ValueError, 'Unaccepted'):
            run_case.verify_publications(self.out, self.state)

    def test_both_boundaries_reopen_without_replaying_physical_stages(self):
        self.execute(sticky='post_place post_route')
        events = self.recorded()
        self.assertEqual(events.count('apply'), 1)
        self.assertEqual(events.count('regional_apply'), 1)
        self.assertEqual(events.count('place'), 1)
        self.assertEqual(events.count('route'), 1)
        self.assertEqual([x['return_code'] for x in self.state['stages']], [75, 75, 0])
        self.assertLess(events.index('rf_verify:_resume_post_place:post_place'), events.index('route'))
        self.assertLess(events.index('rf_verify:_resume_post_route:post_route'),
                        len(events) - 1)
        self.assertFalse(any(x.startswith('restore:_resume_post_route') for x in events))
        self.assertFalse((self.out / 'recovery/pending.txt').exists())
        self.assertTrue((self.out / 'post_route.dcp').is_file())
        self.assertTrue(all(x['acceptance'].startswith('PASS:') for x in self.state['recoveries']))

    def test_route_resume_never_places(self):
        self.execute(sticky='resume_place post_route', mode='route')
        self.assertEqual(self.recorded().count('place'), 0)
        self.assertEqual(self.recorded().count('route'), 1)
        self.assertTrue((self.out / 'recovery/resume_place_accepted.txt').exists())

    def test_legacy_modes_preserve_physical_stage_counts(self):
        for mode in ['edit', 'place']:
            with self.subTest(mode=mode):
                # Each subcase has a new output and independent evidence.
                self.out = self.root / mode
                self.events = self.root / f'{mode}_events.txt'
                self.execute(sticky='post_place', mode=mode)
                self.assertEqual(self.recorded().count('place'), 1)
                self.assertEqual(self.recorded().count('route'), 1)

    def test_unknown_drift_stops_without_checkpoint_handoff(self):
        with self.assertRaisesRegex(RuntimeError, 'returned 1'):
            self.execute(other='post_place')
        self.assertEqual(len(self.state['stages']), 1)
        self.assertNotIn('route', self.recorded())
        self.assertFalse((self.out / 'recovery').exists())

    def test_raw_reopened_protection_must_pass(self):
        with self.assertRaisesRegex(RuntimeError, 'returned 1'):
            self.execute(sticky='post_place', reopened='protection')
        self.assertEqual(len(self.state['stages']), 2)
        self.assertNotIn('route', self.recorded())
        self.assertFalse((self.out / 'post_place.dcp').exists())
        self.assertFalse((self.out / 'complete.txt').exists())

    def test_reopened_connectivity_failure_stops(self):
        with self.assertRaisesRegex(RuntimeError, 'returned 1'):
            self.execute(sticky='post_route', reopened='structure')
        self.assertEqual(self.recorded().count('route'), 1)
        self.assertFalse((self.out / 'post_route.dcp').exists())

    def test_final_independent_reopen_never_repairs(self):
        self.execute(sticky='post_place resume_place post_route', mode='reopen', stage='reopen')
        self.assertFalse(any(x.startswith('restore:') for x in self.recorded()))
        self.assertNotIn('place', self.recorded())
        self.assertNotIn('route', self.recorded())

    def test_inspect_is_readonly(self):
        self.execute(mode='inspect')
        self.assertEqual(self.recorded(), [])

    def test_regional_off_keeps_original_ff_ce_flow(self):
        self.args.regional = 'off'
        self.execute(sticky='post_place post_route')
        self.assertEqual(self.recorded().count('apply'), 1)
        self.assertEqual(self.recorded().count('place'), 1)
        self.assertEqual(self.recorded().count('route'), 1)
        self.assertNotIn('regional_apply', self.recorded())
        self.assertFalse(any(x.startswith('restore:') for x in self.recorded()))

    def test_no_handoff_for_reopen_stage(self):
        with patch.object(run_case.subprocess, 'run', return_value=SimpleNamespace(returncode=75)):
            with self.assertRaisesRegex(RuntimeError, 'returned 75'):
                run_case.run_stage(self.args, self.code, self.root, self.state,
                                  'reopen', self.input, self.out, 'reopen', None)
        self.assertEqual(len(self.state['stages']), 1)

    def test_unknown_handoff_boundary_is_rejected(self):
        (self.out / 'recovery').mkdir(parents=True)
        (self.out / 'recovery/pending.txt').write_text('../arbitrary\n')
        with patch.object(run_case.subprocess, 'run', return_value=SimpleNamespace(returncode=75)):
            with self.assertRaisesRegex(RuntimeError, 'Unsupported'):
                run_case.run_stage(self.args, self.code, self.root, self.state,
                                  'implementation', self.input, self.out, 'run', None)

    def test_missing_checkpoint_is_rejected(self):
        (self.out / 'recovery').mkdir(parents=True)
        (self.out / 'recovery/pending.txt').write_text('post_place\n')
        with patch.object(run_case.subprocess, 'run', return_value=SimpleNamespace(returncode=75)):
            with self.assertRaisesRegex(RuntimeError, 'Missing recovery artifact'):
                run_case.run_stage(self.args, self.code, self.root, self.state,
                                  'implementation', self.input, self.out, 'run', None)

    def test_repeated_handoff_is_rejected(self):
        self.out.mkdir()
        (self.out / 'recovery').mkdir()
        (self.out / 'recovery/pending.txt').write_text('post_place\n')
        (self.out / 'recovery/post_place.dcp').write_text('checkpoint')
        (self.out / 'plan.tcl').write_text('plan')
        with patch.object(run_case.subprocess, 'run', return_value=SimpleNamespace(returncode=75)):
            with self.assertRaisesRegex(RuntimeError, 'repeated checkpoint recovery'):
                run_case.run_stage(self.args, self.code, self.root, self.state,
                                  'implementation', self.input, self.out, 'run', None)
        self.assertEqual(len(self.state['stages']), 2)

    def test_exit_zero_without_evidence_is_failure(self):
        with patch.object(run_case.subprocess, 'run', return_value=SimpleNamespace(returncode=0)):
            with self.assertRaisesRegex(RuntimeError, 'without completion evidence'):
                run_case.run_stage(self.args, self.code, self.root, self.state,
                                  'implementation', self.input, self.out, 'run', None)


if __name__ == '__main__':
    unittest.main()
