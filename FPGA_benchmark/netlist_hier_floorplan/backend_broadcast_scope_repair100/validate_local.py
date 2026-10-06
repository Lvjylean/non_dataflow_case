"""Validate streamed plans, clock invariants, physical stage recovery and report hooks."""
from pathlib import Path
import ast
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT/'code/regional'))
import test_recovery

original_setup = test_recovery.RecoveryIntegration.setUp


def integrated_setup(self):
    original_setup(self)
    destination = self.root/'runtime/code/regional'
    destination.parent.mkdir(parents=True)
    shutil.move(str(self.code),str(destination))
    self.code=destination
    shutil.copyfile(ROOT/'checkpoint_io.tcl',self.root/'runtime/checkpoint_io.tcl')
    bootstrap=self.code/'bootstrap.tcl'
    bootstrap.write_text(bootstrap.read_text().replace('proc set_param {args} {}', 'set ::test_threads 8\nproc set_param {name value} {set ::test_threads $value}\nproc get_param {name} {return $::test_threads}'))
    (self.root/'runtime/physical_eco.tcl').write_text('namespace eval plg {}\nproc plg::capture {args} {return {}}\nproc plg::release {args} {set ::physical_release_done 1;event physical_release}\nproc plg::place {out args} {place_design {*}$args}\nproc plg::before_route {out} {event physical_gate}\nproc plg::assert_routed {out} {event physical_final}\nset ::physical_release_done 0\nnamespace eval mobility {}\nproc mobility::apply {plan out} {if {!$::physical_release_done} {error "Mobility flags touched before physical release"};event mobility;return $plan}\n')
    # Use the actual production entry, including all audit hooks.
    shutil.copyfile(ROOT/'code/regional/run.tcl',self.code/'run.tcl')
    # Recovery integration mocks the netlist; actual local replication has its own
    # graph tests and native Vivado implementation/reopen tests.
    (self.code/'local_broadcast.tcl').write_text('namespace eval lb {}\nproc lb::install {} {}\n')
    control=self.root/'runtime/control';control.mkdir()
    (control/'audit_active.tcl').write_text('event "audit:$audit_stage"\n')
    (control/'final_fanout.tcl').write_text('proc experiment_final_fanout {out} {event final_fanout}\n')


test_recovery.RecoveryIntegration.setUp=integrated_setup


class Integrated(test_recovery.RecoveryIntegration):
    def test_audit_order_and_single_route(self):
        self.execute(sticky='post_place post_route')
        events=self.recorded()
        self.assertEqual(events.count('place'),1)
        self.assertEqual(events.count('route'),1)
        self.assertEqual(events.count('audit:placed'),1)
        self.assertLess(events.index('audit:placed'),events.index('route'))
        self.assertLess(events.index('physical_gate'),events.index('route'))
        self.assertLess(events.index('physical_release'),events.index('mobility'))

    def test_final_reopen_is_readonly(self):
        self.execute(mode='reopen',stage='reopen')
        events=self.recorded()
        self.assertEqual(events.count('final_fanout'),1)
        self.assertEqual(events.count('audit:routed'),1)
        self.assertNotIn('place',events)
        self.assertNotIn('route',events)


def main():
    out=Path(sys.argv[1]);out.mkdir(parents=True,exist_ok=True)
    results=[]
    python_tests = ['test_generic.py','test_joint_input.py','test_joint_retry.py','test_base_resume.py','test_positive_replay.py']
    python_tests += [name for name in ['test_cone_locality.py',
        'code/regional/test_broadcast_components.py','code/regional/test_locality_plan.py',
        'test_locality_admission.py','test_static_discovery_cache.py'] if (ROOT/name).is_file()]
    for test in python_tests:
        run=subprocess.run([sys.executable,str(ROOT/test)],capture_output=True,text=True)
        results.append(dict(test=test,returncode=run.returncode,output=run.stdout+run.stderr))
    for path in sorted((ROOT/'code/regional').glob('test_*.tcl')):
        run=subprocess.run(['tclsh',str(path)],capture_output=True,text=True)
        results.append(dict(test=path.name,returncode=run.returncode,output=run.stdout+run.stderr))
    run=subprocess.run([sys.executable,str(ROOT/'test_sll_plan.py')],capture_output=True,text=True)
    results.append(dict(test='test_sll_plan.py',returncode=run.returncode,output=run.stdout+run.stderr))
    log=io.StringIO()
    tests=unittest.TextTestRunner(stream=log,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Integrated))
    (out/'integration_tests.txt').write_text(log.getvalue())
    with tempfile.TemporaryDirectory() as td:
        tmp=Path(td)
        tcl_tests = [('test_physical_eco.tcl',[]),('test_clock.tcl',[ROOT/'clock.tcl',tmp/'clock']),('test_stream.tcl',[]),('test_boundary.tcl',[]),('test_limit100.tcl',[]),('test_checkpoint_io.tcl',[]),('test_sll_clock.tcl',[ROOT/'sll_balance.tcl'])]
        for name in ('test_locality_inventory.tcl', 'test_inventory_parent_cache.tcl', 'test_pblock_verify_cache.tcl', 'test_static_discovery_loading.tcl', 'test_scope_audit.tcl', 'test_scope_repair.tcl'):
            if (ROOT/name).is_file():
                tcl_tests.append((name,[]))
        for script,args in tcl_tests:
            run=subprocess.run(['tclsh',str(ROOT/script),*map(str,args)],capture_output=True,text=True)
            results.append(dict(test=script,returncode=run.returncode,output=run.stdout+run.stderr))
        (tmp/'syntax.tcl').write_text('foreach p $argv {set f [open $p]; set s [read $f]; close $f; if {![info complete $s]} {error "Incomplete Tcl: $p"}}\n')
        subprocess.run(['tclsh',str(tmp/'syntax.tcl'),*map(str,ROOT.rglob('*.tcl'))],check=True,capture_output=True)
        for path in ROOT.rglob('*.py'):
            ast.parse(path.read_text(),filename=str(path))
        (tmp/'location.json').write_text(json.dumps(dict(clock_period_ns=8.7,reference_clock_ns=8.8,
            reference_total_s=9439.892613172531,post_opt='fixture',post_opt_sha256='fixture')))
        (tmp/'status.json').write_text(json.dumps(dict(status='STOPPED_WITH_EVIDENCE',compile_seconds=0,
            input_unchanged=True,stages=[])))
        run=subprocess.run([sys.executable,str(ROOT/'report_result.py')],cwd=tmp,
            env=dict(os.environ,COMPILEFAST_RUN_ROOT=str(tmp)),capture_output=True,text=True)
        results.append(dict(test='partial_report',returncode=run.returncode,output=run.stdout+run.stderr))
    summary=dict(status='PASS' if tests.wasSuccessful() and all(x['returncode']==0 for x in results) else 'ERROR',
         integration_tests=tests.testsRun,tests=results,clock_period_ns=6.5,waveform=[0,3.25],
         source_hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in ROOT.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc'})
    (out/'local_validation.json').write_text(json.dumps(summary,indent=2))
    print(json.dumps({k:v for k,v in summary.items() if k not in {'source_hashes','tests'}}))
    if summary['status']!='PASS':
        print(log.getvalue());print(json.dumps(results,indent=2));sys.exit(1)


if __name__=='__main__':
    main()
