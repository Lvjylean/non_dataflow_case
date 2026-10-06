"""Pin-aware macro boundaries and exhaustive scoring parity."""
import itertools
import random
from pathlib import Path
import tempfile
import unittest
from macro_timing import compile_overlay, macros, compress_arcs, native_groups
from cumulative_paths import topology, CumulativePaths, independent_score
from test_control_paths import graph
from test_cumulative_paths import CFG, plan, exhaustive


def fixture(refs,netpins,arcs):
    d=graph(refs,[(a,b) for a,ap,b,bp in netpins])
    for i,c in enumerate(d['cells']):c.update(cell_id=f'c{i}',original_hierarchy='top')
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp);native=root/'native';native.mkdir()
        (native/'macros.tsv').write_text('cell_id\tcell_name\tprimitive\n'+''.join(
            f'c{i}\tc{i}\t{refs[i]}\n' for i in sorted(macros(d))))
        (native/'complete.txt').write_text(f'macros={len(macros(d))}\n')
        (native/'arcs.tsv').write_text('cell_id\tkind\tfrom_pin\tto_pin\n'+''.join(
            f'c{i}\t{k}\t{a}\t{b}\n' for i,k,a,b in arcs))
        nets=root/'nets.tsv';nets.write_text('net_id\ttype\tdrivers\tsinks\n'+''.join(
            f'n{n}\tSIGNAL\tc{a}:{ap}\tc{b}:{bp}\n' for n,(a,ap,b,bp) in enumerate(netpins)))
        overlay=compile_overlay(d,native,nets)
    ids=[f'S{i:02d}' for i in range(len(refs))]
    return topology(d,list(range(len(refs))),ids,overlay),d,overlay


def state(i,inp='D',out='Q'):
    return [(i,'capture',inp,'@state'),(i,'launch','@state',out)]


class MacroTests(unittest.TestCase):
    def score(self,g,slrs):return CumulativePaths(g,CFG).components(plan(slrs),True)

    def test_ff_uram_roundtrip_is_counted(self):
        g,_,_=fixture(['FDRE','LUT1','URAM288'],[(0,'Q',1,'I'),(1,'O',2,'ADDR_A[4]')],state(2,'ADDR_A[4]','DOUT_B[0]'))
        r=self.score(g,[1,0,1]);self.assertEqual(r['cumulative_path_term'],128)
        self.assertEqual(r['cumulative_path_endpoint_histogram'],{2:1})

    def test_ram_to_ff_and_ram_to_ram(self):
        for end in ['FDRE','RAMB36E2','URAM288']:
            arcs=state(0)+([] if end=='FDRE' else state(2))
            g,_,_=fixture(['URAM288','LUT1',end],[(0,'Q',1,'I'),(1,'O',2,'D')],arcs)
            self.assertEqual(self.score(g,[0,1,0])['cumulative_path_term'],128)

    def test_registered_dsp_resets_but_combinational_dsp_does_not(self):
        pins=[(0,'Q',1,'A[0]'),(1,'P[0]',2,'D')]
        registered,_,_=fixture(['FDRE','DSP48E2','FDRE'],pins,state(1,'A[0]','P[0]'))
        comb,_,_=fixture(['FDRE','DSP48E2','FDRE'],pins,[(1,'comb','A[0]','P[0]')])
        self.assertEqual(self.score(registered,[0,1,0])['cumulative_path_term'],0)
        self.assertEqual(self.score(comb,[0,1,0])['cumulative_path_term'],128)

    def test_expanded_dsp_internal_register_boundary(self):
        arcs=[(1,'wire','A[0]','ab/A'),(1,'capture','ab/A','@state'),(1,'launch','@state','ab/Q'),
              (1,'wire','ab/Q','alu/A'),(1,'comb','alu/A','alu/P'),(1,'wire','alu/P','P[0]')]
        g,_,_=fixture(['FDRE','DSP48E2','FDRE'],[(0,'Q',1,'A[0]'),(1,'P[0]',2,'D')],arcs)
        self.assertEqual(self.score(g,[0,1,0])['cumulative_path_term'],0)

    def test_independent_ports_do_not_invent_combinational_paths(self):
        g,_,_=fixture(['FDRE','DSP48E2','FDRE'],[(0,'Q',1,'A'),(1,'P',2,'D')],[(1,'comb','A','ACOUT'),(1,'comb','B','P')])
        self.assertEqual(self.score(g,[0,1,0])['cumulative_path_endpoints'],0)

    def test_multiple_capture_pins_count_original_macro_once(self):
        g,_,_=fixture(['FDRE','LUT1','RAMB36E2'],[(0,'Q',2,'A'),(0,'Q',1,'I'),(1,'O',2,'B')],state(2,'A','Q')+[(2,'capture','B','@state')])
        self.assertEqual(self.score(g,[0,1,0])['cumulative_path_endpoint_histogram'],{2:1})

    def test_exhaustive_assignments_and_incremental_match_independent(self):
        g,_,_=fixture(['URAM288','LUT1','DSP48E2','FDRE'],[(0,'Q',1,'I'),(1,'O',2,'A'),(2,'P',3,'D')],state(0)+[(2,'comb','A','P')])
        m=CumulativePaths(g,dict(CFG,assignment_cache_entries=2))
        for slrs in itertools.product(range(3),repeat=4):
            r=m.components(plan(slrs),True);v=independent_score(g,plan(slrs),CFG)
            self.assertEqual(r['cumulative_path_endpoint_histogram'],v['cumulative_path_endpoint_histogram'])
            self.assertAlmostEqual(r['cumulative_path_term'],exhaustive(g,slrs))
        self.assertGreater(m.stats['incremental_propagations'],0)

    def test_bulk_native_arc_parser_keeps_active_pin_semantics(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)
            (p/'arcs.tsv').write_text('cell_id\tkind\tfrom_pin\tto_pin\n')
            (p/'pins.tsv').write_text('cell_id\tpin\tdirection\tclock\n'
                'c0\tCLK\tIN\t1\nc0\tA[0]\tIN\t0\nc0\tP[0]\tOUT\t0\n')
            (p/'raw_timing.tsv').write_text('cell_id\tarc\n'
                'c0\t{CLK --> A[0] [setup] }\nc0\t{CLK --> P[0] [Reg Clk to Q] }\n')
            cid,rows=list(native_groups(p))[0]
            self.assertEqual(cid,'c0')
            self.assertEqual([(r['kind'],r['from_pin'],r['to_pin']) for r in rows],
                             [('capture','A[0]','@state'),('launch','@state','P[0]')])

    def test_zero_distance_compression_preserves_all_port_dependencies(self):
        rng=random.Random(77)
        roots=['I0','I1','I2','@state'];middle=[f'u{i}/p' for i in range(12)];ends=['O0','O1','@state']
        def reached(edges,start):
            seen=set();queue=[start]
            while queue:
                a=queue.pop()
                for x,b in edges:
                    if x==a and b not in seen:
                        seen.add(b)
                        if b!='@state':queue.append(b)
            return set(ends)&seen
        for _ in range(40):
            nodes=roots+middle
            edges={(a,b) for i,b in enumerate(middle,4) for a in nodes[:i] if rng.random()<.25}
            edges|={(a,b) for a in middle for b in ends if rng.random()<.35}
            rows=[dict(from_pin=a,to_pin=b) for a,b in edges]
            compressed,_=compress_arcs(rows)
            for root in roots:self.assertEqual(reached(edges,root),reached(compressed,root))

    def test_old_cache_rejected_by_new_model(self):
        d=graph(['FDRE','FDRE'],[(0,1)]);old=topology(d,[0,1],['S00','S01'],topology_model='ff_cell_v1')
        with self.assertRaisesRegex(ValueError,'Stale'):CumulativePaths(old,CFG)
        with self.assertRaisesRegex(ValueError,'Stale'):independent_score(old,plan([0,1]),CFG)

    def test_combinational_macro_cycle_fails_closed(self):
        with self.assertRaisesRegex(ValueError,'Combinational cycle'):
            fixture(['DSP48E2'],[],[(0,'comb','A','P'),(0,'wire','P','A')])


if __name__=='__main__':unittest.main()
