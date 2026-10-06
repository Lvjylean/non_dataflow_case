"""Locality is opt-in and native proof binds all new bytes and replay dependencies."""
import argparse
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from run_case import (admit_base_replay, locality_environment, seed_base_closure,
                      sha, source_hashes, validate_locality_admission, write)


class LocalityAdmission(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root/'source'
        files = {
            'chain.tcl': 'source $compilefast_code/clock.tcl\nsource $compilefast_code/code/base/seed.tcl\nsource $compilefast_code/code/regional/run.tcl\n',
            'clock.tcl': '# unchanged clock\n',
            'checkpoint_io.tcl': '# unchanged checkpoint IO\n',
            'spatial_policy.tcl': '# unchanged spatial policy\n',
            'sll_balance.tcl': '# unchanged SLL\nsource $plan\n',
            'code/base/seed.tcl': 'source [file join [file dirname [info script]] ../../physical_eco.tcl]\nsource $here/../../control/performance_base.tcl\n',
            'physical_eco.tcl': '# unchanged physical base\n',
            'control/performance_base.tcl': 'source [file join [file dirname [info script]] performance_common.tcl]\n',
            'control/performance_common.tcl': '# unchanged batching\n',
            'code/regional/run.tcl': '# new generic code\n',
            'code/regional/locality_physical.tcl': '# new generic-only overlay\n',
        }
        for name, content in files.items():
            path = self.source/name;path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        self.old = self.root/'old';self.new = self.root/'new'
        for folder in [self.old/'base/pre_route', self.old/'seed', self.new]:
            folder.mkdir(parents=True)
        self.checkpoint = self.old/'base/pre_route.dcp';self.checkpoint.write_bytes(b'placed')
        (self.old/'base/complete.txt').write_text('complete')
        (self.old/'base/pre_route/timing_summary.rpt').write_text('ap_clk {0 3.25} 6.5\n')
        write(self.old/'source_manifest.json', source_hashes(self.source))
        write(self.old/'status.json', dict(status='COMPLETE_REVIEW_CRITERIA',active_pid=None,compile_seconds=123))
        write(self.old/'location.json',dict(post_opt_sha256='clean',clock_period_ns=6.5,fanout_required_lt=100))
        for folder in [self.old,self.new]:write(folder/'input_manifest.json',dict(files={'regions.tcl':'same'}))
        self.args = argparse.Namespace(expected_sha256='clean',period=6.5,clock_port='ap_clk',broadcast_locality=True,fixture=False)

    def evidence(self):
        hashes = source_hashes(self.source)
        return dict(status='PASS', source_hashes=hashes,
                    native_broadcast_locality_pass=True,
                    native_locality_evidence=dict(status='PASS',source_hashes=hashes,
                        implementation_pass=True,independent_reopen_pass=True))

    def replay(self):
        write(self.new/'tests/local_results.json',self.evidence())
        return admit_base_replay(self.old,sha(self.checkpoint),self.new,self.source,self.args)

    def test_native_proof_requires_new_pass_implementation_and_reopen(self):
        for key in ['native_broadcast_locality_pass','native_locality_evidence']:
            evidence = self.evidence();evidence.pop(key)
            with self.assertRaises(ValueError):validate_locality_admission(evidence,self.source)
        for key in ['status','implementation_pass','independent_reopen_pass']:
            evidence=self.evidence();evidence['native_locality_evidence'][key]=False
            with self.assertRaises(ValueError):validate_locality_admission(evidence,self.source)
        validate_locality_admission(self.evidence(),self.source)

    def test_old_or_partial_hashes_cannot_authorize_new_physical_code(self):
        evidence=self.evidence()
        evidence['native_locality_evidence']=copy.deepcopy(evidence['native_locality_evidence'])
        evidence['native_locality_evidence']['source_hashes']['code/regional/run.tcl']='old'
        with self.assertRaisesRegex(ValueError,'bound'):validate_locality_admission(evidence,self.source)
        evidence=self.evidence()
        (self.source/'code/regional/run.tcl').write_text('changed after native proof')
        with self.assertRaisesRegex(ValueError,'complete current'):validate_locality_admission(evidence,self.source)
        evidence=self.evidence();evidence['source_hashes'].pop('physical_eco.tcl')
        with self.assertRaisesRegex(ValueError,'complete current'):validate_locality_admission(evidence,self.source)

    def test_added_unvalidated_file_rejected(self):
        evidence=self.evidence();(self.source/'injected.tcl').write_text('new source')
        with self.assertRaises(ValueError):validate_locality_admission(evidence,self.source)

    def test_environment_explicitly_controls_both_process_paths(self):
        with patch.dict(os.environ, {'BL_LOCALITY':'stale'}, clear=False):
            env=dict(os.environ)
            locality_environment(env,False)
            self.assertNotIn('BL_LOCALITY',env);self.assertNotIn('BL_LOCALITY',os.environ)
            locality_environment(env,True)
            self.assertEqual(env['BL_LOCALITY'],'1');self.assertEqual(os.environ['BL_LOCALITY'],'1')

    def test_replay_accepts_new_generic_overlay_only_after_native_revalidation(self):
        (self.source/'code/regional/locality_physical.tcl').write_text('# verified new overlay')
        result=self.replay()
        self.assertTrue(result['native_locality_revalidated'])
        self.assertIn('physical_eco.tcl',result['seed_base_source_hashes'])
        self.assertIn('control/performance_common.tcl',result['seed_base_source_hashes'])
        self.assertNotIn('code/regional/locality_physical.tcl',result['seed_base_source_hashes'])
        self.assertTrue((self.new/'base').is_symlink())

    def test_replay_rejects_changed_transitive_physical_or_batching_dependency(self):
        for name in ['physical_eco.tcl','control/performance_common.tcl','code/base/seed.tcl']:
            path=self.source/name;old=path.read_text();path.write_text(old+'# changed')
            with self.assertRaisesRegex(ValueError,'dependency changed'):self.replay()
            self.assertFalse((self.new/'base').exists());path.write_text(old)

    def test_replay_rejects_changed_base_file_set_or_dynamic_source(self):
        path=self.source/'code/base/new.tcl';path.write_text('# new')
        with self.assertRaisesRegex(ValueError,'file set'):self.replay()
        path.unlink()
        (self.source/'control/performance_common.tcl').write_text('source $unknown_runtime_path\n')
        with self.assertRaisesRegex(ValueError,'Unresolved'):seed_base_closure(self.source)

    def test_replay_requires_proof_even_when_base_hashes_match(self):
        write(self.new/'tests/local_results.json',dict(status='PASS'))
        with self.assertRaisesRegex(ValueError,'native integration'):
            admit_base_replay(self.old,sha(self.checkpoint),self.new,self.source,self.args)
        self.assertFalse((self.new/'base').exists())

    def test_disabled_switch_preserves_old_strict_physical_change_rule(self):
        self.args.broadcast_locality=False
        (self.source/'code/regional/locality_physical.tcl').write_text('# changed')
        with self.assertRaisesRegex(ValueError,'Unexpected change'):self.replay()


class LocalityController(unittest.TestCase):
    @unittest.skipUnless(Path('/proc/meminfo').exists(), 'Controller memory admission requires Linux')
    def test_explicit_switch_survives_retry_and_disabled_clears_parent_environment(self):
        code = Path(__file__).resolve().parent
        for enabled in [False, True]:
            with self.subTest(enabled=enabled), tempfile.TemporaryDirectory() as td:
                root = Path(td);inp = root/'input.dcp';inp.write_bytes(b'clean')
                fp = root/'floorplan';fp.mkdir()
                validation = root/'validation.json';write(validation,dict(status='PASS'))
                fake = root/'vivado'
                fake.write_text('#!'+sys.executable+'\n'+'''import json,os,sys
from pathlib import Path
argv=sys.argv;tail=argv[argv.index('-tclargs')+1:]
if argv[argv.index('-source')+1].endswith('/chain.tcl'):
    root=Path(tail[2]);impl=root/'generic/implementation'
    (root/'base').mkdir();(root/'base/pre_route.dcp').write_bytes(b'placed')
else:
    impl=Path(tail[1]);root=impl.parents[1]
    assert Path(tail[0]).read_bytes()==b'placed'
(impl/'joint_placed').mkdir(parents=True)
(impl/'joint_placed/reject_ids.json').write_text('["candidate@SLR0"]')
with (root/'observed_env.txt').open('a') as stream:
    stream.write(os.environ.get('BL_LOCALITY','disabled')+'\\n')
sys.exit(77)
''')
                fake.chmod(0o755)
                run = root/'run'
                command = [sys.executable,str(code/'run_case.py'),'--input',str(inp),
                    '--expected-sha256',sha(inp),'--floorplan',str(fp),'--period','6.5',
                    '--work-root',str(run),'--validation-json',str(validation),'--vivado',str(fake),
                    '--memory-required-gib','0','--fixture']
                if enabled:command.append('--broadcast-locality')
                subprocess.run(command,env=dict(os.environ,BL_LOCALITY='stale'),capture_output=True,text=True)
                state=json.loads((run/'status.json').read_text())
                self.assertIn('Bounded joint timing retry',state['error'])
                self.assertEqual((run/'observed_env.txt').read_text().splitlines(),
                                 ['1' if enabled else 'disabled']*2)
                self.assertEqual(json.loads((run/'location.json').read_text())['broadcast_locality'],enabled)


if __name__=='__main__':unittest.main()
