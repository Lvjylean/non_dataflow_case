"""Check register boundaries, path binding and protected control attachments."""
import copy
import json
from pathlib import Path
import unittest
import tempfile
from collections import Counter

from control_path_cost import PathModel, bind_paths, parse_timing
from control_cones import discover
from control_path_refine import Refinement, complete_run
from improve import digest
from edge_padding import region_from_crs
from static_regions import RESOURCES

CFG=json.loads(Path(__file__).with_name('control_path_config.json').read_text())


def graph(refs,edges,names=None):
    names=names or [f'c{i}' for i in range(len(refs))]
    return dict(cells=[dict(cell_name=n,primitive=r) for n,r in zip(names,refs)],
                atoms=[[i] for i in range(len(refs))],atom_of=list(range(len(refs))),
                nets=[(f'n{i}',a,[b],4) for i,(a,b) in enumerate(edges)])


def report(ids,names=None,rank=1,slack=.2):
    names=names or [f'c{i}' for i in ids]
    return dict(rank=rank,cells=names,cell_ids=ids,source=names[0]+'/Q',
                sink=names[-1]+'/D',slack_ns=slack,requirement_ns=8,criticality=4.)


def score(data,slrs,paths=()):
    model=PathModel(data,dict(paths=paths),CFG)
    owners=[f'S{s}' for s in slrs]
    regions={m:dict(slrs=[s]) for m,s in zip(owners,slrs)}
    return model.evaluate(owners,regions,True)


class CumulativePathTests(unittest.TestCase):
    def test_roundtrip_accumulates_every_adjacent_boundary(self):
        d=graph(['FDRE','LUT2','FDRE'],[(0,1),(1,2)])
        r=score(d,[3,1,2],[report([0,1,2])])
        self.assertEqual(r['maximum_boundaries'],3)
        self.assertEqual(r['weighted_path_square'],16)
        self.assertEqual(r['observed_paths'][0]['extra_boundaries'],2)
        self.assertEqual(score(d,[2,1,2])['weighted_path_square'],1)

    def test_zero_or_one_boundary_has_no_square_penalty(self):
        d=graph(['FDRE','LUT1','FDRE'],[(0,1),(1,2)])
        for slrs in ([1,1,1],[1,2,2]):
            self.assertEqual(score(d,slrs)['weighted_path_square'],0)

    def test_register_stops_accumulation_between_cycles(self):
        d=graph(['FDRE','FDRE','FDRE'],[(0,1),(1,2)])
        r=score(d,[0,1,2]);self.assertEqual(r['maximum_boundaries'],1)
        self.assertEqual(r['endpoints_over_one'],0)

    def test_reconvergent_paths_count_endpoint_once(self):
        d=graph(['FDRE','LUT1','LUT1','FDRE'],[(0,1),(0,2),(1,3),(2,3)])
        r=score(d,[0,2,2,0],[report([0,1,3]),report([0,2,3],rank=2)])
        self.assertEqual(r['supported_endpoint_count'],1)
        self.assertEqual(r['weighted_path_square'],4*9)

    def test_opaque_macro_interior_is_not_invented(self):
        d=graph(['FDRE','DSP48E2','FDRE'],[(0,1),(1,2)])
        self.assertEqual(score(d,[0,1,2])['supported_endpoint_count'],0)
        r=score(d,[0,1,2],[report([0,1,2])])
        self.assertEqual(r['maximum_boundaries'],2)

    def test_unreachable_comb_edges_do_not_create_path(self):
        d=graph(['LUT1','LUT1','FDRE'],[(0,1),(1,2)])
        self.assertEqual(score(d,[0,2,0])['supported_endpoint_count'],0)

    def test_unsupported_multidie_region_fails_explicitly(self):
        d=graph(['FDRE','FDRE'],[(0,1)])
        model=PathModel(d,dict(paths=[]),CFG)
        with self.assertRaisesRegex(ValueError,'single-SLR'):
            model.evaluate(['S','S'],{'S':dict(slrs=[0,1])})

    def test_combinational_cycle_fails_explicitly(self):
        d=graph(['FDRE','LUT1','LUT1'],[(0,1),(1,2),(2,1)])
        with self.assertRaisesRegex(ValueError,'cycle'):PathModel(d,dict(paths=[]),CFG)

    def test_exact_binding_deduplicates_and_retains_worst_slack(self):
        d=graph(['FDRE','LUT1','FDRE'],[(0,1),(1,2)])
        paths=[report([0,1,2]),report([0,1,2],rank=2,slack=.1)]
        r=bind_paths(d,paths,CFG)
        self.assertEqual(r['coverage']['accepted_reports'],2)
        self.assertEqual(len(r['paths']),1)
        self.assertEqual(r['paths'][0]['rank'],2)

    def test_binding_rejects_unknown_and_missing_original_edge(self):
        d=graph(['FDRE','LUT1','FDRE'],[(0,1)])
        paths=[report([0,1,2]),report([0,1,2],['c0','replica','c2'],rank=2)]
        r=bind_paths(d,paths,CFG)
        self.assertEqual({p['reason'] for p in r['excluded']},
                         {'no_original_directed_edge','unmapped_original_cell'})

    def test_identity_projection_requires_original_direct_edge(self):
        d=graph(['FDRE','FDRE'],[(0,1)])
        p=report([0,1],['c0','f96_identity_12','c1'])
        r=bind_paths(d,[p],CFG)
        self.assertEqual(r['paths'][0]['cell_ids'],[0,1])
        d['nets']=[];self.assertEqual(bind_paths(d,[p],CFG)['coverage']['accepted_reports'],0)

    def test_interior_register_rejected_even_in_reported_trace(self):
        d=graph(['FDRE','FDRE','FDRE'],[(0,1),(1,2)])
        r=bind_paths(d,[report([0,1,2])],CFG)
        self.assertEqual(r['excluded'][0]['reason'],'interior_state_boundary')

    def test_wrapped_timing_rows_ignore_pblock_name(self):
        text='''Slack (MET) : 0.200ns
  Source: top/ap_start_reg/Q
  Destination: top/ap_CS_fsm_reg/D
  Requirement: 8.000ns
 SLICE  FDRE (Prop_fdre_C_Q)  0.1 top/hfp_S09
                     top/ap_start_reg/Q
 SLICE  net (fanout=1) 0.1 top/n
 SLICE  LUT2 (Prop_lut2_I0_O) 0.2 top/hfp_S04
                     top/done/O
 SLICE FDRE top/ap_CS_fsm_reg/D
'''
        p=parse_timing(text)[0]
        self.assertEqual(p['cells'],['top/ap_start_reg','top/done','top/ap_CS_fsm_reg'])

    def test_local_shell_and_capture_cone_keep_protected_chain_intact(self):
        names=['top/unit/ap_start_reg','top/unit/ap_done','top/ap_CS_fsm_i',
               'top/ap_CS_fsm_reg','top/unit/uram']
        d=graph(['FDRE','LUT1','LUT1','FDRE','URAM288'],[(0,1),(1,2),(2,3)],names)
        p=report([0,1,2,3],names[:4]);joint=[dict(hierarchy='top/unit/@joint_0',atoms=[4])]
        r=discover(d,dict(paths=[p]),joint,joint,['S3','S3','S1','S2','G2'],CFG)
        shell,cone=r['units']
        self.assertEqual(shell['atoms'],[0,1]);self.assertEqual(shell['preferred'],'G2')
        self.assertEqual(cone['atoms'],[2]);self.assertEqual(cone['preferred'],'S2')
        self.assertNotIn(4,{a for u in r['units'] for a in u['atoms']})

    def test_shared_control_fanin_does_not_merge_endpoints(self):
        names=['top/ap_start','top/shared','top/ap_CS_fsm_a','top/ap_CS_fsm_b']
        d=graph(['FDRE','LUT1','FDRE','FDRE'],[(0,1),(1,2),(1,3)],names)
        paths=[report([0,1,k],[names[i] for i in [0,1,k]],rank=k) for k in [2,3]]
        r=discover(d,dict(paths=paths),[],[],['S0','S0','S1','S2'],CFG)
        self.assertEqual(r['shared_atoms_retained'],1);self.assertEqual(r['units'],[])

    def test_large_control_component_is_not_made_atomic(self):
        names=['top/ap_start','top/shared','top/ap_CS_fsm']
        d=graph(['FDRE','LUT1','FDRE'],[(0,1),(1,2)],names)
        r=discover(d,dict(paths=[report([0,1,2],names)]),[],[],['S0','S1','S2'],
                   dict(CFG,max_control_unit_cells=0))
        self.assertFalse(r['units']);self.assertTrue(r['rejected'])


class RefinementGuards(unittest.TestCase):
    def test_completion_hashes_final_progress_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp);(out/'summary.json').write_text('{}')
            def progress(row):
                with (out/'progress.jsonl').open('a') as f:f.write(json.dumps(row)+'\n')
            complete_run(out,progress,1.,2,3.)
            certificate=json.loads((out/'complete.json').read_text())
            self.assertTrue(all(digest(out/p)==h for p,h in certificate['files'].items()))
            with self.assertRaises(FileExistsError):complete_run(out,progress,1.,2,3.)

    def model(self):
        d=graph(['FDRE','LUT1','FDRE','LUT1'],[(0,1),(1,2)])
        d['atom_resources']=[Counter(FF=1),Counter(LUT=1),Counter(FF=1),Counter(LUT=1)]
        d['edges']=[((0,1),4),((1,2),4)]
        owners=['S3','S1','S2','S1'];ids=['S1','S2','S3']
        device={f'X0Y{s}':dict(x=0,y=s,slr=s,resources={r:100 for r in RESOURCES}) for s in [1,2,3]}
        regions={f'S{s}':region_from_crs([f'X0Y{s}'],device) for s in [1,2,3]}
        modules=[]
        for m in ids:
            q=Counter()
            for a,owner in enumerate(owners):
                if owner==m:q.update(d['atom_resources'][a])
            modules.append(dict(module_id=m,cells=owners.count(m),**{r:q[r] for r in RESOURCES}))
        cfg=dict(CFG,core_soft_strength=.1,cut_weight=1.,logical_core_weight=1.)
        dc=dict(resource_limits={r:.7 for r in RESOURCES},directed_weight=1.,
                slr_distance_weight=8.,branch_square_weight=32.)
        class Budget:
            def fits(self,q):return True
        unit=dict(id='CTRL0000',kind='capture_cone',atoms=[1],options=['S2','S1'],ranks=[1])
        return Refinement(d,owners,dict(modules=modules),regions,{m:m for m in ids},device,
                          dc,cfg,dict(paths=[report([0,1,2])]),[unit],[],Budget())

    def test_atomic_move_lowers_cost_and_restore_recovers_state(self):
        m=self.model();before=m.score();original=copy.deepcopy(m.demands)
        old=m.move(m.units[0],'S2')
        self.assertTrue(m.legal());self.assertEqual(m.score()['path_square_term'],0)
        self.assertLess(m.score()['J_control'],before['J_control'])
        m.restore(old)
        self.assertEqual(m.demands,original);self.assertEqual(m.score(),before)
        m.repair(lambda row:None);self.assertEqual(m.owners[1],'S2')

    def test_hard_resource_limit_rejects_path_improving_move(self):
        m=self.model();m.regions['S2']['capacity']['LUT']=0
        m.repair(lambda row:None)
        self.assertEqual(m.owners[1],'S1');self.assertFalse(m.history)

    def test_cut_budget_is_enforced_independently_of_path_gain(self):
        m=self.model();m.initial_cut=0
        old=m.move(m.units[0],'S2')
        self.assertFalse(m.legal());m.restore(old)


if __name__=='__main__':unittest.main()
