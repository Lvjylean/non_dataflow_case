"""Binding and module-count checks for the cache-only floorplan entry."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import floorplan_cached


class CachedFloorplanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        source = root/'code/connection_partition'
        source.mkdir(parents=True)
        cfg=json.loads((floorplan_cached.SOURCE/'directed_config.json').read_text())
        cfg['hypernet_model']='all_atom_v1'
        (source/'directed_config.json').write_text(json.dumps(cfg))
        adapter = root/'code/balanced_implementation/adapter.tcl'
        adapter.parent.mkdir(parents=True)
        adapter.write_text('# test adapter\n')
        self.source_patch = patch.object(floorplan_cached, 'SOURCE', source)
        self.source_patch.start()
        self.addCleanup(self.source_patch.stop)
        self.previous = root/'previous'
        export = self.previous/'input/export'
        export.mkdir(parents=True)
        (export/'modules.json').write_text(json.dumps(dict(
            modules=[dict(module_id=f'S{i:02d}') for i in range(12)])))
        (export/'static_regions.json').write_text('{}')
        (self.previous/'input/original_regions.json').write_text('{}')
        (self.previous/'input/cr.tsv').write_text('cr\n')
        (self.previous/'netmodel.pkl').write_bytes(b'bound synthetic cache')
        (self.previous/'directed.json').write_text('{}')
        self.binding = dict(input_dcp='/fixture/post_opt.dcp',
                            input_sha256='a'*64)
        (self.previous/'binding.json').write_text(json.dumps(self.binding))
        self.output = root/'output'

    def test_fresh_design_binding_accepts_twelve_modules(self):
        (self.previous/'local_binding.json').write_text(json.dumps(dict(
            source_sha256={'netmodel.pkl':floorplan_cached.sha(
                self.previous/'netmodel.pkl')})))
        floorplan_cached.prepare(self.output, self.previous, [])
        self.assertEqual(len(json.loads(
            (self.output/'input/export/modules.json').read_text())['modules']), 12)

    def test_fresh_design_binding_rejects_wrong_cache(self):
        (self.previous/'local_binding.json').write_text(json.dumps(dict(
            source_sha256={'netmodel.pkl':'0'*64})))
        with self.assertRaisesRegex(ValueError, 'Net-model cache'):
            floorplan_cached.prepare(self.output, self.previous, [])

    def test_legacy_immutable_binding_still_works(self):
        self.binding['immutable_files'] = {
            'input/netmodel.pkl':floorplan_cached.sha(self.previous/'netmodel.pkl')}
        (self.previous/'binding.json').write_text(json.dumps(self.binding))
        floorplan_cached.prepare(self.output, self.previous, [])
        self.assertTrue((self.output/'source/adapter_reference.tcl').is_file())

    def test_new_model_rejects_old_bound_cache_before_writing(self):
        cfg_path=floorplan_cached.SOURCE/'directed_config.json'
        cfg=json.loads(cfg_path.read_text());cfg['hypernet_model']='boundary_spatial_v1'
        cfg_path.write_text(json.dumps(cfg))
        (self.previous/'local_binding.json').write_text(json.dumps(dict(
            source_sha256={'netmodel.pkl':floorplan_cached.sha(self.previous/'netmodel.pkl')})))
        with self.assertRaisesRegex(ValueError,'Hypernet model changed'):
            floorplan_cached.prepare(self.output,self.previous,[])
        self.assertFalse(self.output.exists())


if __name__ == '__main__':
    unittest.main()
