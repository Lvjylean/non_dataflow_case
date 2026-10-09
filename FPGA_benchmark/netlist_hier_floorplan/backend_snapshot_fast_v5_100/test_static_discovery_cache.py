import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('static_cache', HERE/'code/regional/static_discovery_cache.py')
cache = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cache)


class StaticDiscoveryCacheTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.code = self.root/'code'; self.code.mkdir()
        (self.code/'fixture.tcl').write_text('# native source\n')
        self.manifest = self.root/'source_manifest.json'
        cache.write(self.manifest, cache.code_inventory(self.code))
        self.dcp = self.root/'base.dcp'; self.dcp.write_bytes(b'immutable fixture checkpoint')
        self.source = self.root/'first'; self.source.mkdir()
        self.target = self.root/'retry'; self.target.mkdir()
        self.context = cache.make_context(self.dcp, self.code, self.manifest, '2023.2', 'xcu250',
                                          '{ap_clk 6.7 {0.000 3.350}}', 'live_base')
        cache.write(self.source/'static_context.json', self.context)
        for name in cache.FILES:
            (self.source/name).write_text('driver\tsink\nfirst/O\tlast/D\n')
        (self.source/'metadata.tsv').write_text('key\tvalue\nschema\tlocality-inventory-v1\nstatus\tPASS\n')
        cache.write(self.source/'proposals.json', {'schema': 'broadcast-locality-v1', 'requests': []})
        (self.source/'requests.tcl').write_text('set bl_requests {}\n')
        cache.publish(self.source)
        self.retry_context = dict(self.context, producer_state='reopened_base')
        cache.write(self.target/'static_context.json', self.retry_context)

    def miss(self):
        result = cache.restore(self.source, self.target)
        self.assertEqual(result['status'], 'MISS')
        self.assertFalse(any((self.target/n).exists() for n in cache.FILES))
        return result

    def test_exact_six_files_hit_without_failed_plan(self):
        (self.source/'final_plan.tcl').write_text('error NEVER_REUSE_FAILED_PLAN')
        result = cache.restore(self.source, self.target)
        self.assertEqual(result['status'], 'HIT')
        for name in cache.FILES:
            self.assertEqual((self.source/name).read_bytes(), (self.target/name).read_bytes())
        self.assertFalse((self.target/'final_plan.tcl').exists())

    def test_each_output_corruption_misses(self):
        for name in cache.FILES:
            original = (self.source/name).read_bytes()
            (self.source/name).write_bytes(original+b'changed')
            self.miss()
            (self.source/name).write_bytes(original)

    def test_each_output_missing_misses(self):
        for name in cache.FILES:
            data = (self.source/name).read_bytes()
            (self.source/name).unlink()
            self.miss()
            (self.source/name).write_bytes(data)

    def test_changed_checkpoint_misses(self):
        self.dcp.write_bytes(b'changed baseline checkpoint')
        self.miss()

    def test_changed_or_added_source_misses(self):
        (self.code/'new.tcl').write_text('# unbound source')
        self.miss()

    def test_context_fields_cannot_be_relaxed(self):
        for name, value in [('vivado_version', '2024.1'), ('part', 'other'), ('clocks', '{ap_clk 9 {0 4.5}}'),
                            ('prepare_parameters', {}), ('source_manifest_sha256', 'bad')]:
            cache.write(self.target/'static_context.json', dict(self.retry_context, **{name:value}))
            self.miss()
        cache.write(self.target/'static_context.json', self.retry_context)

    def test_saved_producer_state_missing_or_unknown_rejected(self):
        original = json.loads((self.source/'static_cache.json').read_text())
        for state in ('post_edit', '', None):
            saved = json.loads(json.dumps(original))
            if state is None:
                del saved['context']['producer_state']
            else:
                saved['context']['producer_state'] = state
            cache.write(self.source/'static_cache.json', saved)
            self.assertIn('unknown_cache_producer_state', self.miss()['reason'])
        cache.write(self.source/'static_cache.json', original)

    def test_live_session_cannot_restore(self):
        cache.write(self.target/'static_context.json', self.context)
        self.miss()

    def test_incomplete_receipt_rejected(self):
        saved = json.loads((self.source/'static_cache.json').read_text())
        saved['status'] = 'RUNNING'
        cache.write(self.source/'static_cache.json', saved)
        self.miss()

    def test_extra_missing_hash_entry_rejected(self):
        saved = json.loads((self.source/'static_cache.json').read_text())
        del saved['files']['edges.tsv']
        cache.write(self.source/'static_cache.json', saved)
        self.miss()

    def test_publish_revalidates_after_capture(self):
        self.dcp.write_bytes(b'changed during native inventory')
        with self.assertRaisesRegex(ValueError, 'context_changed'):
            cache.publish(self.source)

    def test_source_inventory_ignores_only_runtime_pycache(self):
        pycache = self.code/'__pycache__'; pycache.mkdir()
        (pycache/'fixture.pyc').write_bytes(b'cache')
        self.assertEqual(cache.restore(self.source, self.target)['status'], 'HIT')

    def test_restore_hashes_source_during_copy_without_extra_full_read(self):
        with mock.patch.object(cache, 'sha', wraps=cache.sha) as digest:
            result = cache.restore(self.source, self.target)
        self.assertEqual(result['status'], 'HIT')
        source_outputs = {self.source/name for name in cache.FILES}
        self.assertFalse(any(Path(call.args[0]) in source_outputs for call in digest.call_args_list))
        for name in cache.FILES:
            self.assertTrue(any(Path(call.args[0]) == self.target/(name+'.cache.tmp')
                                for call in digest.call_args_list))

    def test_checkpoint_change_during_copy_cannot_publish(self):
        original = cache.copy_hashed
        def changed(source, target):
            result = original(source, target)
            self.dcp.write_bytes(b'checkpoint changed during the long cache copy')
            return result
        with mock.patch.object(cache, 'copy_hashed', side_effect=changed):
            result = self.miss()
        self.assertIn('context_changed_during_capture', result['reason'])
        self.assertFalse(list(self.target.glob('*.cache.tmp')))

    def test_destination_corruption_after_stream_copy_cannot_publish(self):
        original = cache.copy_hashed
        def corrupted(source, target):
            result = original(source, target)
            Path(target).write_bytes(b'corrupt persisted destination')
            return result
        with mock.patch.object(cache, 'copy_hashed', side_effect=corrupted):
            result = self.miss()
        self.assertIn('cache_copy_changed', result['reason'])
        self.assertFalse(list(self.target.glob('*.cache.tmp')))

    def test_duplicate_metadata_keys_rejected(self):
        with (self.source/'metadata.tsv').open('a') as stream:
            stream.write('status\tPASS\n')
        self.assertIn('duplicate_inventory_metadata', self.miss()['reason'])


if __name__ == '__main__':
    unittest.main()
