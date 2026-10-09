"""Unit regressions for the comparator; these fixtures are not native proofs."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('probe_verifier', HERE/'verify_static_discovery_cache_probe.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)
cache = probe.module(HERE)


class ProbeComparisonTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.code = self.root/'source'
        (self.code/'code/regional').mkdir(parents=True)
        (self.code/'code/regional/static_discovery_cache.py').write_bytes(
            (HERE/'code/regional/static_discovery_cache.py').read_bytes())
        self.out = self.root/'unit_comparator_fixture'
        (self.out/'base').mkdir(parents=True)
        self.checkpoint = self.out/'base/pre_route.dcp'
        self.checkpoint.write_bytes(b'unit fixture, never a native checkpoint')
        self.hashes = cache.code_inventory(self.code)
        cache.write(self.out/'source_manifest.json', self.hashes)
        cache.write(self.out/'exclude.json', ['ff/Q@SLR1'])
        for stage in ('live', 'fresh', 'cached'):
            folder = self.out/stage/'locality'
            folder.mkdir(parents=True)
            for name in cache.FILES:
                (folder/name).write_text('driver\tsink\nff/Q\treceiver/D\n')
            (folder/'metadata.tsv').write_text('key\tvalue\nschema\tlocality-inventory-v1\nstatus\tPASS\n')
            cache.write(folder/'proposals.json', {'schema': 'broadcast-locality-v1', 'requests': []})
            (folder/'requests.tcl').write_text('set bl_requests {}\n')
            context = cache.make_context(self.checkpoint, self.code, self.out/'source_manifest.json',
                                         '2023.2', 'xcu250', '{clk 10 {0 5}}',
                                         'live_base' if stage == 'live' else 'reopened_base')
            cache.write(folder/'static_context.json', context)
            (self.out/stage/'native_context.tsv').write_text(
                f'key\tvalue\nmode\t{stage}\nvivado_version\t2023.2\npart\txcu250\n'
                f'checkpoint\t{self.checkpoint}\ndiscovery_ms\t1000\n')
            (self.out/stage/'NATIVE_COMPLETE').write_text('unit marker\n')
            cache.write(self.out/stage/'joint_candidates.json',
                        {'keep': ['ff/Q@SLR1', 'other/Q@SLR2'] if stage == 'live' else ['other/Q@SLR2']})
            (folder/'final_plan.tcl').write_text('set plan unit\n')
            (self.out/stage/'native_plan.tcl').write_text('set native_plan unit\n')
            for relative in probe.FRESH_NATIVE_TABLES:
                (self.out/stage/relative).write_text('key\tvalue\none\tfirst\ntwo\tsecond\n')
        saved = cache.publish(self.out/'live/locality')
        cached = self.out/'cached/locality'
        cache.write(cached/'static_cache_restore.json',
                    {'status': 'HIT', 'context': json.loads((cached/'static_context.json').read_text()),
                     'files': saved['files'], 'seconds': .1})

    def compare(self):
        return probe.compare(self.code, self.out)

    def test_complete_evidence_and_fresh_native_tables_required(self):
        result = self.compare()
        self.assertEqual(result['schema'], probe.PROOF_SCHEMA)
        self.assertTrue(result['fresh_native_inputs_and_timing_equivalent'])
        self.assertTrue(result['retry_native_plan_equivalent'])
        self.assertEqual(result['native_discovery_seconds']['cached'], 1)

    def test_native_timing_or_config_mismatch_rejected(self):
        for relative in (*probe.FRESH_NATIVE_TABLES, 'native_plan.tcl'):
            path = self.out/'cached'/relative
            before = path.read_bytes()
            path.write_bytes(before.replace(b'first', b'changed') if path.suffix == '.tsv' else b'different native plan')
            with self.assertRaisesRegex(ValueError, 'Native fresh/cached retry admission differs'):
                self.compare()
            path.write_bytes(before)

    def test_table_order_can_change_but_duplicates_cannot(self):
        path = self.out/'cached/ji_edges.tsv'
        path.write_text('key\tvalue\ntwo\tsecond\none\tfirst\n')
        self.compare()
        with path.open('a') as stream:
            stream.write('one\tfirst\n')
        with self.assertRaisesRegex(ValueError, 'differs'):
            self.compare()

    def test_nonempty_exclusion_must_actually_remove_selected_ids(self):
        cache.write(self.out/'cached/joint_candidates.json', {'keep': ['ff/Q@SLR1']})
        with self.assertRaisesRegex(ValueError, 'did not exclude'):
            self.compare()

    def test_native_context_mismatch_rejected(self):
        path = self.out/'cached/native_context.tsv'
        path.write_text(path.read_text().replace('part\txcu250', 'part\tother'))
        with self.assertRaisesRegex(ValueError, 'Native context mismatch'):
            self.compare()

    def test_receipt_not_bound_to_target_context_rejected(self):
        path = self.out/'cached/locality/static_cache_restore.json'
        receipt = json.loads(path.read_text())
        receipt['context']['clocks'] = '{clk 9 {0 4.5}}'
        cache.write(path, receipt)
        with self.assertRaisesRegex(ValueError, 'receipt identity differs'):
            self.compare()


if __name__ == '__main__':
    unittest.main()
