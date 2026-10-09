"""Structural regression tests; these do not claim native placement/STA proof."""
import copy
import unittest

from broadcast_components import discover, plan_component


class Design:
    def __init__(self):
        self.cells = {}
        self.nets = {}

    def cell(self, name, ref='LUT1', slr='SLR0', x=0, y=0, editable=True, init="2'h2"):
        self.cells[name] = dict(ref=ref, slr=slr, x=x, y=y,
                                config={'INIT': init}, inputs={}, editable=editable)
        return name

    def edge(self, driver, sink):
        self.nets.setdefault(driver, []).append(sink)
        if '/' not in sink:return
        c, p = sink.rsplit('/', 1)
        if c in self.cells:
            self.cells[c]['inputs'][p] = driver

    def load(self, name, driver, slr='SLR0', x=0, y=0, editable=True):
        self.cell(name, 'FDRE', slr, x, y, editable)
        self.edge(driver, name + '/D')

    def root(self):
        self.cell('ff', 'FDRE', 'SLR1', 3, 6, init="1'b0")

    def component(self, minimum=16):
        return discover(self.cells, self.nets, minimum)['components']['ff/Q']

    def plan(self, slr='SLR0', limit=96):
        return plan_component(self.component(), slr, 'copy0', self.cells, self.nets, limit)


def logical_roots(cells, nets):
    owners = {}
    for driver, sinks in nets.items():
        for sink in sinks:
            if sink in owners:
                raise AssertionError('multiply driven:' + sink)
            owners[sink] = driver
    def trace(pin):
        output = owners[pin]
        cell = output.rsplit('/', 1)[0]
        seen = set()
        while cells[cell]['ref'] == 'LUT1' and cells[cell]['config']['INIT'] == "2'h2":
            if cell in seen:
                raise AssertionError('cycle')
            seen.add(cell)
            output = owners[cell + '/I0']
            cell = output.rsplit('/', 1)[0]
        return output
    return {pin: trace(pin) for pin in owners if cells.get(pin.rsplit('/', 1)[0], {}).get('ref') == 'FDRE'}


def realize(d, plan):
    cells, nets = copy.deepcopy(d.cells), copy.deepcopy(d.nets)
    cells['copy0'] = copy.deepcopy(cells['ff'])
    cells['copy0']['slr'] = plan['metadata']['target_slr']
    for name, info in plan['clones'].items():
        cells[name] = copy.deepcopy(info)
    for key, sinks in plan['expected'].items():
        nets[key] = list(sinks)
    return cells, nets


class BroadcastTests(unittest.TestCase):
    def hidden(self):
        d = Design(); d.root()
        for i in range(4):
            slr = 'SLR0' if i < 2 else 'SLR1'
            d.cell('b' + str(i), slr=slr, x=i, y=0)
            d.edge('ff/Q', 'b' + str(i) + '/I0')
            for j in range(48):
                d.load(f's{i}_{j}', f'b{i}/O', slr, i, j % 4)
        return d

    def test_unrelated_native_port_boundary_is_retained(self):
        d=self.hidden(); d.cell("external", "FDRE", editable=False)
        d.edge("barrier PORT:data[0]", "external/D")
        d.edge("external/Q", "barrier PORT:result")
        self.assertEqual(d.component()["effective_fanout"],192)

    def test_hidden_effective_fanout_and_pure_cut(self):
        d = self.hidden(); c = d.component()
        self.assertEqual((c['direct_fanout'], c['effective_fanout']), (4, 192))
        p = d.plan()
        self.assertFalse(p['clones'])
        self.assertEqual(p['rewires'], {'b0/I0': 'copy0/Q', 'b1/I0': 'copy0/Q'})
        self.assertEqual(p['expected']['copy0/Q'], ['b0/I0', 'b1/I0'])
        self.assertEqual(p['expected']['ff/Q'], ['b2/I0', 'b3/I0'])
        self.assertNotIn('b0/O', p['expected'])
        self.assertEqual(p['metadata']['reused_nodes'], ['b0', 'b1'])

    def test_remote_single_slr_not_rejected(self):
        d = Design(); d.root(); d.cell('b'); d.edge('ff/Q', 'b/I0')
        for i in range(32): d.load(f's{i}', 'b/O')
        self.assertEqual(list(d.component()['terminals']), ['SLR0'])
        self.assertEqual(d.plan()['rewires'], {'b/I0': 'copy0/Q'})

    def test_large_target_group_has_real_capped_tree(self):
        d = Design(); d.root(); d.cell('b', slr='SLR1'); d.edge('ff/Q', 'b/I0')
        for i in range(300): d.load(f's{i}', 'b/O', x=i % 8, y=i // 8)
        p = d.plan()
        self.assertEqual(len(p['clones']), 4)
        self.assertEqual(len(p['expected']['copy0/Q']), 4)
        self.assertTrue(all(len(v) <= 96 for k, v in p['expected'].items() if k not in d.nets))
        self.assertEqual(len(p['rewires']), 300)
        self.assertEqual(p['metadata']['added_lut_levels'], 1)
        self.assertTrue(all(c['origin'] == 'b' for c in p['clones'].values()))

    def test_mixed_tree_preserves_remote_and_local_pin_ownership(self):
        d = Design(); d.root(); d.cell('mixed', slr='SLR1'); d.edge('ff/Q', 'mixed/I0')
        for i in range(40): d.load(f's{i}', 'mixed/O', 'SLR0' if i % 2 else 'SLR1')
        before = logical_roots(d.cells, d.nets)
        p = d.plan(); cells, nets = realize(d, p)
        after = logical_roots(cells, nets)
        for pin, root in before.items():
            self.assertEqual(after[pin], 'copy0/Q' if int(pin.split('/')[0][1:]) % 2 else root)
        self.assertEqual(len(nets['mixed/O']), 20)
        self.assertEqual(nets['ff/Q'], ['mixed/I0'])

    def test_nonidentity_is_terminal_not_transparent(self):
        d = self.hidden(); d.cell('invert', init="2'h1"); d.edge('ff/Q', 'invert/I0')
        d.load('behind_inverse', 'invert/O')
        c = d.component()
        self.assertNotIn('invert', c['transparent'])
        self.assertIn('invert/I0', c['terminals']['SLR0'])
        self.assertNotIn('behind_inverse/D', c['terminals']['SLR0'])

    def test_protected_and_clock_boundaries_untouched(self):
        d = self.hidden()
        d.cell('protected', editable=False); d.edge('ff/Q', 'protected/I0')
        d.load('behind_protected', 'protected/O')
        d.cell('clk_sink', 'FDRE'); d.edge('ff/Q', 'clk_sink/C')
        c = d.component(); p = d.plan()
        self.assertIn('protected/I0', c['barriers'])
        self.assertIn('clk_sink/C', c['barriers'])
        self.assertNotIn('behind_protected/D', p['rewires'])
        self.assertIn('protected/I0', p['expected']['ff/Q'])
        self.assertIn('clk_sink/C', p['expected']['ff/Q'])

    def test_protected_leaf_prevents_whole_subtree_rewire(self):
        d = Design(); d.root(); d.cell('b'); d.edge('ff/Q', 'b/I0')
        for i in range(20): d.load(f's{i}', 'b/O')
        d.load('protected', 'b/O', editable=False)
        p = d.plan()
        self.assertNotIn('b/I0', p['rewires'])
        self.assertEqual(p['expected']['b/O'], ['protected/D'])

    def test_nonlocal_intermediate_prevents_pure_reuse(self):
        d = Design(); d.root(); d.cell('b'); d.cell('far', slr='SLR1')
        d.edge('ff/Q', 'b/I0'); d.edge('b/O', 'far/I0')
        for i in range(20): d.load(f's{i}', 'far/O')
        p = d.plan()
        self.assertEqual(p['metadata']['reused_subtrees'], [])
        self.assertEqual(len(p['rewires']), 20)

    def test_same_source_has_one_component_no_nested_owner(self):
        d = self.hidden()
        result = discover(d.cells, d.nets)
        self.assertEqual(list(result['components']), ['ff/Q'])
        self.assertNotIn('b0/O', result['components'])

    def test_multiple_levels_strict_cap_and_logic_equivalence(self):
        d = Design(); d.root(); d.cell('b', slr='SLR1'); d.edge('ff/Q', 'b/I0')
        for i in range(80): d.load(f's{i}', 'b/O')
        p = d.plan(limit=4); cells, nets = realize(d, p)
        self.assertGreaterEqual(p['metadata']['added_lut_levels'], 3)
        self.assertTrue(all(len(v) <= 4 for k, v in p['expected'].items() if k not in d.nets))
        self.assertEqual(set(logical_roots(cells, nets).values()), {'copy0/Q'})

    def test_no_input_mutation_and_deterministic_plan(self):
        d = self.hidden(); saved = copy.deepcopy((d.cells, d.nets)); c = d.component()
        saved_c = copy.deepcopy(c)
        a = plan_component(c, 'SLR0', 'copy0', d.cells, d.nets)
        b = plan_component(c, 'SLR0', 'copy0', d.cells, d.nets)
        self.assertEqual(a, b); self.assertEqual((d.cells, d.nets), saved); self.assertEqual(c, saved_c)

    def test_stale_boundary_and_duplicate_driver_fail_closed(self):
        d = self.hidden(); c = d.component(); d.load('extra', 'b0/O')
        with self.assertRaisesRegex(ValueError, 'stale_component_boundary'):
            plan_component(c, 'SLR0', 'copy0', d.cells, d.nets)
        d = self.hidden(); d.nets['b1/O'].append('s0_0/D')
        with self.assertRaisesRegex(ValueError, 'multiple_sink_drivers'):
            discover(d.cells, d.nets)

    def test_uneditable_root_is_not_a_candidate(self):
        d = self.hidden(); d.cells['ff']['editable'] = False
        r = discover(d.cells, d.nets)
        self.assertFalse(r['components'])
        self.assertEqual(r['decisions']['ff/Q'], 'unsupported_or_protected_root')


if __name__ == '__main__':
    unittest.main()
