"""Regression tests for checkpoint-bound case input and optional report baselines."""
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import unittest

from run_case import validate_floorplan, sha

CODE = Path(__file__).resolve().parent


class GenericInput(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root/'export').mkdir()
        (self.root/'regions.tcl').write_text('set planned_regions {}\n')
        (self.root/'membership.tsv').write_text('cell\tmodule\tresource\tref\nff\tG00\tFF\tFDRE\n')
        (self.root/'export/modules.json').write_text(json.dumps({'modules':[{'module_id':'G00','cells':1}]}))
        self.manifest = dict(status='PASS',input_sha256='checkpoint',module_count=1,counts={'G00':1},
            files={p:sha(self.root/p) for p in ['regions.tcl','membership.tsv','export/modules.json']})
        self.save()

    def save(self):
        (self.root/'manifest.json').write_text(json.dumps(self.manifest))

    def test_variable_module_count_and_prefix(self):
        self.assertEqual(validate_floorplan(self.root,'checkpoint')['module_count'],1)

    def test_checkpoint_mismatch(self):
        with self.assertRaisesRegex(ValueError,'different checkpoint'):
            validate_floorplan(self.root,'another')

    def test_modified_membership(self):
        with (self.root/'membership.tsv').open('a') as f:
            f.write('ff2\tG00\tFF\tFDRE\n')
        with self.assertRaisesRegex(ValueError,'manifest mismatch'):
            validate_floorplan(self.root,'checkpoint')

    def test_inconsistent_module_counts(self):
        self.manifest['counts']['G00'] = 2
        self.save()
        with self.assertRaisesRegex(ValueError,'counts differ'):
            validate_floorplan(self.root,'checkpoint')

    def test_case_report_without_reference(self):
        (self.root/'location.json').write_text(json.dumps(dict(case_name='GETRF',module_count=9,
            clock_port='system_clock',clock_period_ns=10,reference_total_s=None,
            post_opt='fixture',post_opt_sha256='checkpoint')))
        (self.root/'status.json').write_text(json.dumps(dict(status='STOPPED_WITH_EVIDENCE',
            compile_seconds=0,input_unchanged=True,stages=[])))
        subprocess.run([sys.executable,str(CODE/'report_result.py')],
            env=dict(os.environ,COMPILEFAST_RUN_ROOT=str(self.root)),capture_output=True,check=True)
        result=json.loads((self.root/'result.json').read_text())
        self.assertIsNone(result['gates']['compile_time_reduced'])
        report=(self.root/'report/实验报告.md').read_text()
        self.assertEqual(report.count('\n## '),7)
        self.assertIn('GETRF',report)
        self.assertNotIn('TRTRS',report)
        self.assertNotIn('figures/regions.png',report)


if __name__ == '__main__':
    unittest.main()
