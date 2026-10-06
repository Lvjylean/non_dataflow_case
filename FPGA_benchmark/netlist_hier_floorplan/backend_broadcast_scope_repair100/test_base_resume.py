"""Validate that a discovery recovery cannot reuse incompatible physical work."""
import argparse
from pathlib import Path
import tempfile
import unittest
from run_case import admit_base_resume, sha, write


class Resume(unittest.TestCase):
    def test_verified_resume_and_changed_input_guards(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);old=p/'old';new=p/'new';source=p/'source'
            for d in [old/'base',old/'seed',old/'generic/implementation',new,source]:
                d.mkdir(parents=True)
            (old/'base/pre_route.dcp').write_bytes(b'valid placed checkpoint')
            (old/'base/complete.txt').write_text('complete')
            phase=old/'generic/implementation/phase.txt';phase.write_text('123\tdiscovery\n')
            (source/'chain.tcl').write_text('unchanged seed/base')
            write(old/'source_manifest.json',{'chain.tcl':sha(source/'chain.tcl')})
            write(old/'status.json',dict(status='STOPPED_WITH_EVIDENCE',active_pid=None,compile_seconds=123))
            write(old/'location.json',dict(post_opt_sha256='clean',clock_period_ns=6.7,fanout_required_lt=100))
            for d in [old,new]:write(d/'input_manifest.json',{'files':{'regions.tcl':'same'}})
            args=argparse.Namespace(expected_sha256='clean',period=6.7)
            digest=sha(old/'base/pre_route.dcp')
            for change,restore in [
                (lambda:phase.write_text('123\tapply\n'),lambda:phase.write_text('123\tdiscovery\n')),
                (lambda:setattr(args,'period',6.8),lambda:setattr(args,'period',6.7)),
                (lambda:(source/'chain.tcl').write_text('changed'),lambda:(source/'chain.tcl').write_text('unchanged seed/base')),
                (lambda:write(new/'input_manifest.json',{'files':{}}),lambda:write(new/'input_manifest.json',{'files':{'regions.tcl':'same'}}))]:
                change()
                with self.assertRaises(ValueError):admit_base_resume(old,digest,new,source,args)
                restore()
            with self.assertRaises(ValueError):admit_base_resume(old,'wrong',new,source,args)
            evidence=admit_base_resume(old,digest,new,source,args)
            self.assertEqual(evidence['prior_compile_seconds'],123)
            self.assertEqual((new/'base/pre_route.dcp').read_bytes(),b'valid placed checkpoint')
            self.assertTrue((new/'base').is_symlink())
            self.assertTrue((old/'generic/implementation/phase.txt').exists())


if __name__=='__main__':unittest.main()
