"""Temporary positive-WNS policy and completed-checkpoint replay safeguards."""
import argparse
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from run_case import admit_base_replay, sha, write

ROOT=Path(__file__).resolve().parent
def load(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/'code/regional'/f'{name}.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
gate=load('joint_gate');planner=load('joint_input')


class PositiveGate(unittest.TestCase):
    def setUp(self):
        self.old=dict(wns=.131,tns=0,whs=.001,ths=0)
        self.new=dict(wns=.093,tns=0,whs=.001,ths=0)
        self.before={('ff/D','max'):.131,('ff/D','min'):.001}
        self.after=dict(self.before)
        self.after.update({('copy/D','max'):.093,('copy/D','min'):.001})
        self.mapping=[dict(pin='copy/D',original='ff/D',owner='a')]
        self.candidates=dict(keep=['a','b'],owners={'a':['shared'],'b':['shared']})

    def evaluate(self,policy='positive'):
        return gate.evaluate(self.before,self.after,self.mapping,self.old,self.new,self.candidates,policy)

    def test_positive_degradation_changes_only_explicit_policy(self):
        self.assertFalse(self.evaluate('nonworse')['accepted'])
        result=self.evaluate()
        self.assertTrue(result['accepted'])
        self.assertFalse(result['global_nonworse'])
        self.assertTrue(result['global_policy_pass'])
        self.assertEqual(result['reject_ids'],[])

    def test_zero_negative_and_nan_wns_rejected(self):
        for value in [0,-.001,float('nan')]:
            self.new['wns']=value
            self.assertFalse(self.evaluate()['accepted'])

    def test_hold_and_tns_rules_remain(self):
        for field,value in [('whs',-.001),('ths',-.001),('tns',-.001)]:
            old=self.new[field];self.new[field]=value
            self.assertFalse(self.evaluate()['accepted'])
            self.new[field]=old

    def test_missing_or_negative_affected_endpoint_rejected(self):
        for key in list(self.after):
            old=self.after.pop(key)
            self.assertFalse(self.evaluate()['accepted'])
            self.after[key]=-.001
            self.assertFalse(self.evaluate()['accepted'])
            self.after[key]=old

    def test_shared_groups_still_rejected_atomically(self):
        self.after[('copy/D','max')]=-.001
        self.assertEqual(self.evaluate()['reject_ids'],['a','b'])

    def test_unknown_policy_rejected(self):
        with self.assertRaises(ValueError):self.evaluate('disabled')


class BaseReplay(unittest.TestCase):
    @unittest.skipUnless(Path('/proc/meminfo').exists(),'Controller memory admission requires Linux')
    def test_controller_replay_policy_and_stale_exclusion_cleanup(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);old=p/'old';root=p/'new';fp=p/'floorplan';fp.mkdir()
            for folder in [old/'base/pre_route',old/'seed']:folder.mkdir(parents=True)
            inp=p/'clean.dcp';inp.write_bytes(b'clean')
            checkpoint=old/'base/pre_route.dcp';checkpoint.write_bytes(b'placed')
            (old/'base/complete.txt').write_text('complete')
            (old/'base/pre_route/timing_summary.rpt').write_text('ap_clk {0 3.25} 6.5\n')
            write(old/'source_manifest.json',{})
            write(old/'status.json',dict(status='COMPLETE_REVIEW_CRITERIA',active_pid=None,compile_seconds=123))
            write(old/'location.json',dict(post_opt_sha256=sha(inp),clock_period_ns=6.5,fanout_required_lt=100))
            write(old/'input_manifest.json',dict(input_sha256=sha(inp),files={}))
            expected=p/'expected.json';write(expected,dict(keep=['candidate']))
            val=p/'validation.json';write(val,dict(status='PASS'))
            fake=p/'vivado'
            fake.write_text('#!'+sys.executable+'\n'+'''import os,sys,json
from pathlib import Path
a=sys.argv
assert a[a.index('-source')+1].endswith('/code/regional/run.tcl')
assert os.environ['JI_WNS_POLICY']=='positive'
assert 'JI_EXCLUDE' not in os.environ
assert json.loads(Path(os.environ['JI_EXPECTED_PLAN']).read_text())['keep']==['candidate']
assert Path(a[a.index('-tclargs')+1]).read_bytes()==b'placed'
print('REPLAY_ENV_PASS')
sys.exit(42)
''');fake.chmod(0o755)
            run=subprocess.run([sys.executable,str(ROOT/'run_case.py'),'--input',str(inp),
                '--expected-sha256',sha(inp),'--floorplan',str(fp),'--period','6.5','--work-root',str(root),
                '--validation-json',str(val),'--vivado',str(fake),'--memory-required-gib','0','--fixture',
                '--joint-wns-policy','positive','--replay-base-root',str(old),
                '--replay-base-sha256',sha(checkpoint),'--expected-joint-plan',str(expected)],
                env=dict(os.environ,JI_EXCLUDE='/stale/reject.json',JI_EXPECTED_PLAN='/stale/plan.json'),
                capture_output=True,text=True)
            state=json.loads((root/'status.json').read_text())
            self.assertIn('returned 42',state['error'])
            self.assertIn('REPLAY_ENV_PASS',(root/'generic_base_replay_console.log').read_text())
            self.assertFalse(state['stages'][0]['included_in_compile_time'])
            self.assertEqual((old/'base/pre_route.dcp').read_bytes(),b'placed')

    def test_completed_input_and_physical_source_guards(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);old=p/'old';new=p/'new';source=p/'source'
            for d in [old/'base/pre_route',old/'seed',new,source]:d.mkdir(parents=True)
            checkpoint=old/'base/pre_route.dcp';checkpoint.write_bytes(b'placed')
            (old/'base/complete.txt').write_text('complete')
            clock=old/'base/pre_route/timing_summary.rpt';clock.write_text('ap_clk {0.000 3.250} 6.500\n')
            src=source/'physical_eco.tcl';src.write_text('unchanged')
            write(old/'source_manifest.json',{'physical_eco.tcl':sha(src)})
            state=dict(status='COMPLETE_REVIEW_CRITERIA',active_pid=None,compile_seconds=123)
            write(old/'status.json',state)
            write(old/'location.json',dict(post_opt_sha256='clean',clock_period_ns=6.5,fanout_required_lt=100))
            for d in [old,new]:write(d/'input_manifest.json',{'files':{'regions.tcl':'same'}})
            args=argparse.Namespace(expected_sha256='clean',period=6.5,clock_port='ap_clk')
            digest=sha(checkpoint)
            mutations=[
                (lambda:write(old/'status.json',dict(state,active_pid=123)),lambda:write(old/'status.json',state)),
                (lambda:write(old/'status.json',dict(state,status='RUNNING')),lambda:write(old/'status.json',state)),
                (lambda:setattr(args,'period',6.7),lambda:setattr(args,'period',6.5)),
                (lambda:clock.write_text('ap_clk {0 3.35} 6.7\n'),lambda:clock.write_text('ap_clk {0 3.25} 6.5\n')),
                (lambda:src.write_text('changed'),lambda:src.write_text('unchanged')),
                (lambda:write(new/'input_manifest.json',{}),lambda:write(new/'input_manifest.json',{'files':{'regions.tcl':'same'}})),
                (lambda:write(old/'sll_input.json',{}),lambda:(old/'sll_input.json').unlink()),
            ]
            for change,restore in mutations:
                change()
                with self.assertRaises(ValueError):admit_base_replay(old,digest,new,source,args)
                self.assertFalse((new/'base').exists())
                restore()
            with self.assertRaises(ValueError):admit_base_replay(old,'wrong',new,source,args)
            evidence=admit_base_replay(old,digest,new,source,args)
            self.assertFalse(evidence['previous_total_included_in_new_runtime'])
            self.assertTrue((new/'base').is_symlink())
            self.assertEqual(sha(checkpoint),digest)

    def test_candidate_identity_covers_connections_and_locations(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);expected=p/'expected.json';evidence=p/'evidence.json'
            plan=dict(keep=['ff/Q@SLR0'],aux={'lut':{'slr':'SLR0'}},links={'copy/D':'lut/O'},hints={'copy':{'x':1}})
            write(expected,plan)
            planner.verify_expected_plan(plan,expected,evidence)
            self.assertEqual(json.loads(evidence.read_text())['status'],'PASS')
            for field in plan:
                different=copy.deepcopy(plan);different[field]=[]
                with self.assertRaises(ValueError):planner.verify_expected_plan(different,expected,evidence)


if __name__=='__main__':unittest.main()
