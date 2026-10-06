"""Exercise actual wait/lease/Tcl forwarding and conservative memory arithmetic."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from policy import BUDGETS, lease_valid, required_available, same_process, write
from vivado_entry import adapt
from controller import assert_queued_inactive

HERE = Path(__file__).resolve().parent


class MemoryTests(unittest.TestCase):
    def test_partial_launch_race_is_detected_before_output_creation(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/'123';p.mkdir()
            (p/'cmdline').write_bytes(b'python3\0runner.py\0--work-root\0/queued/run\0')
            (p/'cwd').symlink_to('/unrelated')
            with self.assertRaises(RuntimeError):
                assert_queued_inactive(Path('/queued/run'), Path(tmp))
            assert_queued_inactive(Path('/different/run'), Path(tmp))

    def test_seed_can_overlap_reserved_heavy_job(self):
        self.assertEqual(required_available(32, 0, [(54, 13)]), 77)
        self.assertGreaterEqual(79, required_available(32, 0, [(54, 13)]))

    def test_two_heavy_phases_are_not_admitted(self):
        self.assertGreater(required_available(54, 26, [(54, 13)]), 53)

    def test_waiting_or_stopped_job_still_occupies_memory(self):
        self.assertEqual(required_available(54, 26, [(54, 13)]), 73)
        # Treating the stopped job as absent would incorrectly allow admission.
        self.assertEqual(required_available(54, 26, []), 32)

    def test_rss_above_reservation_does_not_create_credit(self):
        self.assertEqual(required_available(32, 40, [(54, 60)]), 4)

    def test_negative_values_fail(self):
        with self.assertRaises(ValueError):
            required_available(32, -1, [])

    def test_reopen_overlap(self):
        self.assertEqual(required_available(54, 26, [(32, 18)]), 46)

    def test_lease_identity_and_expiry(self):
        req = dict(stage='generic', nonce='one')
        good = dict(stage='generic', nonce='one', granted=True, expires=20)
        self.assertTrue(lease_valid(good, req, 10))
        self.assertFalse(lease_valid(good, req, 21))
        self.assertFalse(lease_valid(dict(good, nonce='two'), req, 10))
        self.assertFalse(lease_valid(dict(good, stage='base'), req, 10))
        self.assertFalse(lease_valid(dict(good, granted=False), req, 10))

    def test_pid_reuse_and_foreign_directory_rejected(self):
        p = dict(pid=123, start_ticks=20, cmd_sha256='abc', cwd='/owned')
        self.assertTrue(same_process(p, dict(p)))
        self.assertFalse(same_process(p, dict(p, start_ticks=21)))
        self.assertFalse(same_process(p, dict(p, cwd='/other')))

    def test_native_argv_preserved(self):
        config = dict(second_root='/owned/run', gate_directory='/owned/gates')
        native = ['-mode', 'batch', '-source', '/owned/run/flow/chain.tcl',
                  '-log', '/owned/run/a.log', '-tclargs', 'input', 'checkpoint', '/owned/run']
        out, env = adapt(native, config, HERE)
        self.assertEqual(out[:3]+out[4:], native[:3]+native[4:])
        self.assertEqual(env['PHASE_NATIVE_SCRIPT'], native[3])
        self.assertEqual(env['PHASE_FLOW_ROOT'], '/owned/run/flow')
        with self.assertRaises(ValueError):
            adapt(['-source', '/foreign/chain.tcl'], config, HERE)

    def test_real_gate_blocks_then_expires_then_grants(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            p = subprocess.Popen([sys.executable, str(HERE/'gate.py'), '--directory', tmp, '--stage', 'generic'],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                deadline = time.monotonic()+5
                while not (d/'request.json').exists():
                    if time.monotonic()>deadline:
                        self.fail('Gate did not request memory')
                    time.sleep(.02)
                request = json.loads((d/'request.json').read_text())
                write(d/'grant.json', dict(nonce=request['nonce'], stage='generic', granted=True,
                                          expires=time.time()-1, admission={}))
                time.sleep(.15)
                self.assertIsNone(p.poll())
                self.assertFalse((d/'receipt.json').exists())
                write(d/'grant.json', dict(nonce=request['nonce'], stage='generic', granted=True,
                                          expires=time.time()+10, admission={'available_gib':80}))
                out, err = p.communicate(timeout=5)
                self.assertEqual(p.returncode, 0, err)
                self.assertEqual(json.loads(out)['stage'], 'generic')
                self.assertGreater(json.loads(out)['wait_seconds'], .1)
            finally:
                if p.poll() is None:
                    p.terminate(); p.communicate(timeout=5)

    def test_tcl_trace_preserves_native_source_scope_and_argv(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp); flow = d/'flow'
            for rel in ('code/base/balanced_implementation', 'code/regional'):
                (flow/rel).mkdir(parents=True)
            for rel, label in [('code/base/balanced_implementation/seed_fast.tcl','seed'),
                               ('code/base/balanced_implementation/implement_pre_route.tcl','base'),
                               ('code/regional/run.tcl','generic')]:
                (flow/rel).write_text('lappend ::ran [list '+label+' [file normalize [info script]] $::argv]\n')
            chain = flow/'chain.tcl'
            chain.write_text('set argv {i d run}\n'
                'source $::env(PHASE_FLOW_ROOT)/code/base/balanced_implementation/seed_fast.tcl\n'
                'source $::env(PHASE_FLOW_ROOT)/code/base/balanced_implementation/implement_pre_route.tcl\n'
                'source $::env(PHASE_FLOW_ROOT)/code/regional/run.tcl\n'
                'set argv {i d reopen}\nsource $::env(PHASE_FLOW_ROOT)/code/regional/run.tcl\n'
                'puts "NATIVE $::ran"\n')
            # Intercept only the external gate in a Tcl fixture, never physical procedures.
            fixture = d/'fixture.tcl'
            fixture.write_text('rename exec fixture_exec\n'
                'proc exec {args} {lappend ::gate_stages [lindex $args end-1];return fixture}\n'
                'set argv {original arguments}\n'
                'source {'+str(HERE/'entry.tcl')+'}\nputs "GATES $::gate_stages"\n')
            env = dict(os.environ, PHASE_NATIVE_SCRIPT=str(chain), PHASE_FLOW_ROOT=str(flow),
                       PHASE_GATE_TOOL='fixture_gate', PHASE_GATE_DIR=str(d/'gates'))
            out = subprocess.run(['tclsh',str(fixture)],env=env,text=True,capture_output=True)
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertIn('GATES seed base generic reopen',out.stdout)
            self.assertIn(str(flow/'code/regional/run.tcl'),out.stdout)
            self.assertIn('{i d reopen}',out.stdout)


if __name__ == '__main__':
    unittest.main()
