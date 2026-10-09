"""Equivalent planning and bounded work reuse on an immutable stage snapshot."""
import argparse
import contextlib
import copy
import csv
import importlib.util
import json
from pathlib import Path
import random
import tempfile
import time
import types
import unittest
from unittest.mock import patch
import sys


ROOT = Path(__file__).resolve().parent


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT/'code/regional'/f'{name}.py')
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


cone = module('cone_locality')
joint = module('joint_input')
sys.path.insert(0, str(ROOT/'code/regional'))
locality = module('locality_plan')
sys.path.pop(0)


def cell(ref, slr='SLR1', inputs=None):
    return dict(ref=ref, slr=slr, x=3, y=5 if slr == 'SLR1' else 2,
                config={'INIT': "2'h2"}, inputs=inputs or {}, editable=True)


def cone_inventory(count=8, unrelated=0):
    cells = {}
    for i in range(count):
        prefix = f'cone{i}_'
        cells.update({prefix+'src': cell('FDRE'),
                      prefix+'a': cell('LUT1', 'SLR0', {'I0': prefix+'src/Q'}),
                      prefix+'b': cell('LUT1', 'SLR0', {'I0': prefix+'a/O'}),
                      prefix+'local': cell('LUT1', inputs={'I0': prefix+'b/O'}),
                      prefix+'end': cell('URAM288', inputs={'BWE_A[7]': prefix+'local/O'})})
    nets = {}
    for name, obj in cells.items():
        for pin, source in obj['inputs'].items():
            nets.setdefault(source, []).append(name+'/'+pin)
    # Unrelated nets exercise the old per-candidate global snapshot cost.
    nets.update({f'unrelated{i}/O': [f'load{i}/D'] for i in range(unrelated)})
    return cells, nets, cone.discover(cells, nets)['candidates']


def joint_inventory():
    def edge(key):
        return dict(key=key, kind='ordinary', source_cell=key.rsplit('/', 1)[0])
    cells = {}
    for name, ref, slr, y in [('src', 'FDRE', 'SLR1', 5), ('a', 'LUT1', 'SLR0', 2),
                              ('b', 'LUT1', 'SLR1', 5), ('ff', 'FDRE', 'SLR1', 5)]:
        cells[name] = dict(name=name, ref=ref, slr=slr, x=2, y=y, period=6.7)
    return types.SimpleNamespace(cells=cells,
        edges={'src': {}, 'a': {'I0': edge('src/Q')}, 'b': {'I0': edge('a/O')},
               'ff': {'D': edge('b/O'), 'CE': dict(key='ONE', kind='constant', source_cell='')}},
        cones={'ff/Q': {'a', 'b'}}, loads={'src/Q': 1, 'a/O': 1, 'b/O': 1, 'ff/Q': 32},
        slacks={'ff/D': dict(max='0.7', min='0.1', requirement='6.7')},
        candidates=[dict(id='ff/Q@SLR0', key='ff/Q', replica='sbeco_local_ff_1_SLR0',
            ref='FDRE', target='SLR0', x='2', y='2', loads='16', driver='b/O',
            driver_cell='b', status='supported')])


class SnapshotReuse(unittest.TestCase):
    @staticmethod
    def table(path, headers, records):
        with path.open('w') as stream:
            writer = csv.DictWriter(stream, fieldnames=headers, delimiter='\t')
            writer.writeheader(); writer.writerows(records)

    def test_finish_admission_and_all_serialized_outputs_equal(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)/'locality'; folder.mkdir()
            cells, nets, candidates = cone_inventory(count=8, unrelated=0)
            records = [dict(name=name, ref=obj['ref'], slr=obj['slr'], x=obj['x'], y=obj['y'],
                            init=obj['config']['INIT'], editable='1', status='')
                       for name, obj in cells.items()]
            self.table(folder/'cells.tsv', list(records[0]), records)
            self.table(folder/'edges.tsv', ['driver', 'sink'],
                       [dict(driver=key, sink=pin) for key, pins in nets.items() for pin in pins])
            # Use proposals generated from exactly the serialized native inputs.
            cells, nets = locality.inventory(folder)
            candidates = locality.locality.discover(cells, nets)['candidates']
            (folder/'proposals.json').write_text(json.dumps(dict(requests=[], cones=candidates, decisions=[])))
            self.table(folder/'template_status.tsv', ['cell', 'status'],
                       [dict(cell=name, status='supported') for name in cells])
            self.table(folder/'through_slacks.tsv',
                       ['key', 'max', 'status', 'start_clock', 'end_clock', 'period', 'requirement'],
                       [dict(key=c['root'], max='.3', status='supported', start_clock='clk',
                             end_clock='clk', period='6.7', requirement='6.7') for c in candidates])
            edges = {name: {pin: dict(key=key, kind='ordinary', source_cell=key.rsplit('/', 1)[0])
                            for pin, key in obj['inputs'].items()} for name, obj in cells.items()}
            inv = types.SimpleNamespace(cells=cells, edges=edges, candidates=[],
                used={('SLR1', 'LUT'): 0}, capacity={('SLR1', 'LUT'): 1000})
            with patch.object(locality.joint, 'Inventory', return_value=inv), \
                    patch.object(locality.locality, 'Graph', wraps=locality.locality.Graph) as counted:
                with contextlib.redirect_stdout(None): locality.finish(folder)
                self.assertEqual(counted.call_count, 1)
            optimized = [(folder.parent/'joint_candidates.json').read_bytes(),
                         (folder/'final_plan.tcl').read_bytes()]
            self.assertEqual(len(json.loads(optimized[0])['keep']), 8)
            original_plan = locality.locality.plan_candidate
            def fresh_graph(*args, **kwargs):
                kwargs.pop('graph', None)
                return original_plan(*args, **kwargs)
            with patch.object(locality.joint, 'Inventory', return_value=inv), \
                    patch.object(locality.locality, 'plan_candidate', side_effect=fresh_graph):
                with contextlib.redirect_stdout(None): locality.finish(folder)
            self.assertEqual(optimized, [(folder.parent/'joint_candidates.json').read_bytes(),
                                        (folder/'final_plan.tcl').read_bytes()])

    def test_all_cone_outputs_equal_with_one_global_snapshot(self):
        cells, nets, candidates = cone_inventory(count=16, unrelated=4000)
        before = copy.deepcopy((cells, nets, candidates))
        with patch.object(cone, 'Graph', wraps=cone.Graph) as counted:
            expected = [cone.plan_candidate(cells, nets, candidate) for candidate in candidates]
            self.assertEqual(counted.call_count, 16)
        with patch.object(cone, 'Graph', wraps=cone.Graph) as counted:
            graph = cone.Graph(cells, nets)
            actual = [cone.plan_candidate(cells, nets, candidate, graph=graph)
                      for candidate in candidates]
            self.assertEqual(counted.call_count, 1)
        self.assertEqual(actual, expected)
        self.assertEqual((cells, nets, candidates), before)

    def test_rejected_candidate_does_not_poison_later_candidates(self):
        cells, nets, candidates = cone_inventory()
        graph = cone.Graph(cells, nets)
        bad = copy.deepcopy(candidates[0]); bad['clone_cells'] = []
        with self.assertRaisesRegex(cone.LocalityError, 'stale_candidate:clone_cells'):
            cone.plan_candidate(cells, nets, bad, graph=graph)
        actual = [cone.plan_candidate(cells, nets, candidate, graph=graph) for candidate in candidates]
        expected = [cone.plan_candidate(cells, nets, candidate) for candidate in candidates]
        self.assertEqual(actual, expected)

    def test_shared_graph_rejects_another_inventory_identity(self):
        cells, nets, candidates = cone_inventory()
        graph = cone.Graph(cells, nets)
        for other_cells, other_nets in [(copy.deepcopy(cells), nets), (cells, copy.deepcopy(nets))]:
            with self.assertRaisesRegex(cone.LocalityError, 'planning_graph_inventory_mismatch'):
                cone.plan_candidate(other_cells, other_nets, candidates[0], graph=graph)

    def test_joint_position_alternatives_reuse_structure_only(self):
        inv = joint_inventory(); analysis = joint.StructuralAnalysis(inv)
        with patch.object(joint, 'groups', wraps=joint.groups) as counted:
            actual = []
            for x, y in [(2, 2), (2.25, 2), (2.5, 2.25)]:
                inv.candidates[0].update(x=str(x), y=str(y))
                actual.append(joint.build(inv, structural_analysis=analysis))
            self.assertEqual(counted.call_count, 1)
        expected = []
        for x, y in [(2, 2), (2.25, 2), (2.5, 2.25)]:
            inv.candidates[0].update(x=str(x), y=str(y))
            expected.append(joint.build(inv))
        self.assertEqual(actual, expected)
        self.assertEqual((analysis.hits, analysis.misses), (2, 1))

    def test_changed_slack_control_loads_budgets_and_geometry_are_checked_fresh(self):
        mutations = [lambda i: i.slacks['ff/D'].update(max='-.1'),
                     lambda i: i.loads.update({'src/Q': 99, 'a/O': 99}),
                     lambda i: i.cells['src'].update(x=9),
                     lambda i: i.cells['ff'].update(period=6.2),
                     lambda i: i.edges['ff'].update(CE=dict(key='src/Q',kind='ordinary',source_cell='src'))]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                inv = joint_inventory(); analysis = joint.StructuralAnalysis(inv)
                joint.build(inv, structural_analysis=analysis)
                mutation(inv)
                self.assertEqual(joint.build(inv, structural_analysis=analysis), joint.build(inv))
        inv = joint_inventory(); analysis = joint.StructuralAnalysis(inv)
        joint.build(inv, structural_analysis=analysis)
        for kwargs in [{'margin': 3}, {'max_added': 0}, {'per_endpoint': 0},
                       {'excluded': ['ff/Q@SLR0']}]:
            self.assertEqual(joint.build(inv, structural_analysis=analysis, **kwargs), joint.build(inv, **kwargs))

    def test_structural_changes_invalidate_memo_and_failed_mux_is_not_cached(self):
        mutations = [lambda i: i.cells['src'].update(slr='SLR0'),
                     lambda i: i.cells['a'].update(ref='LUT2'),
                     lambda i: i.edges['b']['I0'].update(kind='constant',source_cell='',key='ONE'),
                     lambda i: i.cones['ff/Q'].remove('a')]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                inv = joint_inventory(); analysis = joint.StructuralAnalysis(inv)
                joint.build(inv, structural_analysis=analysis)
                mutation(inv)
                self.assertEqual(joint.build(inv, structural_analysis=analysis), joint.build(inv))
                self.assertEqual(analysis.misses, 2)
        inv = joint_inventory(); inv.cells['b']['ref'] = 'MUXF7'
        inv.edges['b']['I1'] = dict(key='src/Q',kind='ordinary',source_cell='src')
        analysis = joint.StructuralAnalysis(inv)
        for _ in range(2):
            self.assertEqual(joint.build(inv, structural_analysis=analysis), joint.build(inv))
        self.assertEqual(analysis.cache, {})

    def test_joint_analysis_rejects_other_inventory(self):
        inv = joint_inventory(); analysis = joint.StructuralAnalysis(inv)
        other = copy.deepcopy(inv)
        actual = joint.build(other, structural_analysis=analysis)
        self.assertFalse(actual['keep'])
        self.assertEqual(actual['decisions'][0]['status'], 'structural_analysis_inventory_mismatch')

    def test_multi_endpoint_delta_equal_with_one_input_cone_traversal(self):
        inv = joint_inventory(); members = inv.cones['ff/Q']; assignment = {'b': ('SLR0', 2, 2)}
        endpoints = [(('SLR0', x, y), ('SLR0', x, y)) for x, y in [(0, 1), (3, 4), (7, 8)]]
        with patch.object(joint, 'pos', wraps=joint.pos) as observed:
            expected = [joint.delta_bound(inv, 'b', members, assignment, before, after)
                        for before, after in endpoints]
            original_reads = observed.call_count
        with patch.object(joint, 'pos', wraps=joint.pos) as observed:
            actual = joint.delta_bounds(inv, 'b', members, assignment, endpoints)
            batched_reads = observed.call_count
        self.assertEqual(actual, expected)
        self.assertEqual(original_reads, batched_reads*len(endpoints))
        inv.edges['a']['I1'] = dict(key='src/Q',kind='ordinary',source_cell='src')
        expected = [joint.delta_bound(inv, 'b', members, assignment, before, after)
                    for before, after in endpoints]
        self.assertEqual(joint.delta_bounds(inv, 'b', members, assignment, endpoints), expected)

    def test_multi_endpoint_delta_preserves_branch_failure(self):
        inv = joint_inventory(); inv.edges['a']['I0']['source_cell'] = 'missing'
        with self.assertRaisesRegex(KeyError, 'missing'):
            joint.delta_bounds(inv, 'b', inv.cones['ff/Q'], {}, [(('SLR1', 2, 5), ('SLR1', 2, 5))])

    def test_randomized_geometry_slack_and_load_equivalence(self):
        generator = random.Random(81493)
        inv = joint_inventory(); analysis = joint.StructuralAnalysis(inv)
        for _ in range(200):
            inv.candidates[0].update(x=str(generator.uniform(0, 8)), y=str(generator.uniform(0, 8)),
                                     target=generator.choice(['SLR0', 'SLR1', 'SLR2']))
            inv.slacks['ff/D']['max'] = str(generator.uniform(-1, 4))
            inv.loads['src/Q'] = generator.randrange(101)
            self.assertEqual(joint.build(inv, structural_analysis=analysis), joint.build(inv))


def benchmark(net_count=100000, candidate_count=32):
    cells, nets, candidates = cone_inventory(candidate_count, net_count)
    start = time.perf_counter()
    old = [cone.plan_candidate(cells, nets, candidate) for candidate in candidates]
    before = time.perf_counter()-start
    start = time.perf_counter(); graph = cone.Graph(cells, nets)
    new = [cone.plan_candidate(cells, nets, candidate, graph=graph) for candidate in candidates]
    after = time.perf_counter()-start
    if new != old:
        raise AssertionError('Candidate output changed')
    result = dict(status='PASS', workload='synthetic_python_snapshot', nets=len(nets),
                candidates=len(candidates), graph_builds_before=len(candidates), graph_builds_after=1,
                before_seconds=before, after_seconds=after, speedup=before/after)
    inv = joint_inventory(); members = set(); assignment = {}
    for i in range(128):
        name = f'logic{i}'; inv.cells[name] = dict(ref='LUT2', slr='SLR0', x=i%8, y=2, period=6.7)
        previous = 'src' if i == 0 else f'logic{i-1}'
        inv.edges[name] = {'I0': dict(key=previous+('/Q' if i == 0 else '/O'), kind='ordinary', source_cell=previous),
                           'I1': dict(key='src/Q', kind='ordinary', source_cell='src')}
        members.add(name); assignment[name] = ('SLR1', i%8, 5)
    pairs = [(('SLR1', i%8, 5+i/100), ('SLR1', i%8, 5+i/100)) for i in range(64)]
    start = time.perf_counter()
    for _ in range(30):
        old = [joint.delta_bound(inv, 'logic127', members, assignment, *pair) for pair in pairs]
    before = time.perf_counter()-start
    start = time.perf_counter()
    for _ in range(30): new = joint.delta_bounds(inv, 'logic127', members, assignment, pairs)
    after = time.perf_counter()-start
    if old != new:
        raise AssertionError('Endpoint delta changed')
    result['multi_endpoint'] = dict(status='PASS', cone_cells=128, endpoints=64, repeats=30,
        traversals_before=1920, traversals_after=30, before_seconds=before, after_seconds=after,
        speedup=before/after)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--benchmark', action='store_true')
    args, remaining = parser.parse_known_args()
    if args.benchmark:
        print(json.dumps(benchmark(), indent=2))
    else:
        unittest.main(argv=['test_candidate_snapshot_reuse.py', *remaining])
