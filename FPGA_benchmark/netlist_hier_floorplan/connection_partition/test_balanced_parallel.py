"""Focused checks for deterministic, cache-safe parallel proposal generation."""
import json
import multiprocessing as mp
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import balanced_generate as generation


class ParallelProposalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.run = Path(self.tmp.name)
        self.data = dict(
            atoms=[[0], [1], [2]],
            atom_resources=[dict(URAM=320) for _ in range(3)],
            edges=[((0, 1, 2), 4)])
        self.old_globals = tuple(getattr(generation, name) for name in (
            '_RUN', '_DATA', '_AUGMENTED', '_BASELINE', '_CONFIG', '_WEIGHTS'))
        self.addCleanup(self.restore_globals)
        generation._RUN = self.run
        generation._DATA = self.data
        generation._AUGMENTED = self.data
        generation._BASELINE = dict(groups=[[0, 1, 2]], membership=[0, 0, 0])
        generation._CONFIG = dict(split_max_parent_fraction=0.6)
        generation._WEIGHTS = [1, 1, 1]

    def restore_globals(self):
        for name, value in zip((
                '_RUN', '_DATA', '_AUGMENTED', '_BASELINE', '_CONFIG', '_WEIGHTS'),
                self.old_globals):
            setattr(generation, name, value)

    @staticmethod
    def fake_kahypar(_run, _data, vertices, pieces, caps, _weights, _tag, _seed):
        assert len(caps) == pieces
        return [vertices[i::pieces] for i in range(pieces)]

    def test_uniform_serial_and_fork_results_match(self):
        task = ('uniform', 0, 1)
        with patch.object(generation.base, 'run_kahypar', self.fake_kahypar):
            serial = generation.split_task(task)
            if 'fork' not in mp.get_all_start_methods():
                self.skipTest('fork is unavailable')
            with mp.get_context('fork').Pool(2) as pool:
                parallel = pool.map(generation.split_task, [task])[0]
        self.assertEqual(serial, parallel)
        self.assertEqual(serial[1], [[0, 2], [1]])

    def test_existing_candidate_avoids_native_partition(self):
        path = self.run/'candidates/split_p0_s1/groups.json'
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps([[0, 2], [1]])+'\n')
        with patch.object(generation.base, 'run_kahypar',
                          side_effect=AssertionError('unexpected KaHyPar call')):
            _, children, _, reused = generation.split_task(('uniform', 0, 1))
        self.assertEqual(children, [[0, 2], [1]])
        self.assertTrue(reused)

    def test_resource_split_uses_required_number_of_blocks(self):
        with patch.object(generation.base, 'run_kahypar', self.fake_kahypar):
            _, children, _, reused = generation.split_task(('resource', 0, 0))
        self.assertEqual(children, [[0], [1], [2]])
        self.assertFalse(reused)

    def test_indivisible_uniform_parent_is_retained(self):
        generation._DATA = dict(self.data, atoms=[[0, 1, 2]])
        generation._BASELINE = dict(groups=[[0]], membership=[0])
        generation._WEIGHTS = [3]
        with patch.object(generation.base, 'run_kahypar',
                          side_effect=AssertionError('unexpected KaHyPar call')):
            _, children, detail, _ = generation.split_task(('uniform', 0, 0))
        self.assertEqual(children, [[0]])
        self.assertEqual(detail['fraction'], 0)


if __name__ == '__main__':
    unittest.main()
