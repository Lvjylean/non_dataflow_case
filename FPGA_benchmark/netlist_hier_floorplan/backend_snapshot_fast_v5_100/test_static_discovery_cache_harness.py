"""Launch admission and failure tests; no native tool or proof is simulated."""
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('cache_harness', HERE/'run_static_discovery_cache_probe.py')
harness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(harness)


class CacheHarnessTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.code = self.root/'code'
        (self.code/'code/regional').mkdir(parents=True)
        for relative in ('verify_static_discovery_cache_probe.py', 'code/regional/static_discovery_cache.py'):
            (self.code/relative).write_bytes((HERE/relative).read_bytes())
        self.fixture = self.root/'fixture.dcp'
        self.fixture.write_bytes(b'unit admission input')
        probe_spec = importlib.util.spec_from_file_location('admission_probe', self.code/'verify_static_discovery_cache_probe.py')
        verifier = importlib.util.module_from_spec(probe_spec)
        probe_spec.loader.exec_module(verifier)
        self.digest = verifier.module(self.code).sha(self.fixture)
        self.out = self.root/'output'

    def run_probe(self, expected=None, out=None):
        return harness.run(self.code, out or self.out, self.fixture,
                           expected or self.digest, Path('/unit/not-launched/vivado'))

    def test_outputs_inside_source_rejected_before_launch(self):
        with mock.patch.object(harness.subprocess, 'run') as process:
            with self.assertRaisesRegex(ValueError, 'outside the frozen source'):
                self.run_probe(out=self.code/'runtime')
            process.assert_not_called()
        self.assertFalse((self.code/'runtime').exists())

    def test_wrong_fixture_identity_rejected_before_launch(self):
        with mock.patch.object(harness.subprocess, 'run') as process:
            with self.assertRaisesRegex(ValueError, 'Fixture checkpoint identity'):
                self.run_probe(expected='bad')
            process.assert_not_called()
        self.assertFalse(self.out.exists())

    def test_existing_evidence_never_overwritten(self):
        self.out.mkdir()
        (self.out/'keep').write_text('existing evidence')
        with mock.patch.object(harness.subprocess, 'run') as process:
            with self.assertRaises(FileExistsError):
                self.run_probe()
            process.assert_not_called()
        self.assertEqual((self.out/'keep').read_text(), 'existing evidence')

    def test_native_failure_stops_series_and_preserves_log_and_status(self):
        with mock.patch.object(harness.subprocess, 'run', return_value=SimpleNamespace(returncode=2)) as process:
            with self.assertRaisesRegex(ValueError, 'Native live probe failed'):
                self.run_probe()
            self.assertEqual(process.call_count, 1)
        state = json.loads((self.out/'probe_status.json').read_text())
        self.assertEqual(state['status'], 'ERROR')
        self.assertEqual(state['stages'][0]['returncode'], 2)
        self.assertTrue((self.out/'live_console.log').exists())
        self.assertFalse((self.out/'native_static_discovery_cache_evidence.json').exists())

    def test_source_change_stops_before_next_native_process(self):
        def changed_source(*args, **kwargs):
            (self.code/'new.tcl').write_text('# changed after first native call\n')
            return SimpleNamespace(returncode=0)
        with mock.patch.object(harness.subprocess, 'run', side_effect=changed_source) as process:
            with self.assertRaisesRegex(ValueError, 'source changed before fresh'):
                self.run_probe()
            self.assertEqual(process.call_count, 1)
        self.assertEqual(json.loads((self.out/'probe_status.json').read_text())['status'], 'ERROR')


if __name__ == '__main__':
    unittest.main()
