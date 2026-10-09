import importlib.util
import copy
import json
from pathlib import Path
import subprocess
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parent
def module(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/'code/regional'/f'{name}.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
planner=module('joint_input');gate=module('joint_gate')


class Joint(unittest.TestCase):
    def inventory(self):
        i=types.SimpleNamespace(cells={},edges={},cones={'ff/Q':{'a','b'}},loads={},slacks={})
        for name,ref,slr,y in [('src','FDRE','SLR1',5),('a','LUT1','SLR0',2),('b','LUT1','SLR1',5),('ff','FDRE','SLR1',5)]:
            i.cells[name]=dict(name=name,ref=ref,slr=slr,x=2,y=y,period=6.7)
        def edge(key):return dict(key=key,kind='ordinary',source_cell=key.rsplit('/',1)[0])
        i.edges={'src':{},'a':{'I0':edge('src/Q')},'b':{'I0':edge('a/O')},'ff':{'D':edge('b/O'),'CE':dict(key='ONE',kind='constant',source_cell='')}}
        i.loads={'src/Q':1,'a/O':1,'b/O':1,'ff/Q':32}
        i.slacks={'ff/D':dict(max='0.7',min='0.1',requirement='6.7')}
        i.candidates=[dict(id='ff/Q@SLR0',key='ff/Q',replica='sbeco_local_ff_1_SLR0',ref='FDRE',target='SLR0',x='2',y='2',loads='16',driver='b/O',driver_cell='b',status='supported')]
        return i
    def test_backtracking_joint_selected(self):
        p=planner.build(self.inventory())
        self.assertEqual(len(p['keep']),1);self.assertEqual(len(p['aux']),1)
        self.assertEqual(p['estimates']['ff/Q@SLR0']['mode'],'target_local')
        self.assertGreater(p['estimates']['ff/Q@SLR0']['predicted_D_slack'],.7)
    def test_full_mux_atomicity(self):
        i=self.inventory();i.cells['b']['ref']='MUXF7'
        i.edges['b']={'I0':i.edges['b']['I0'],'I1':dict(key='src/Q',kind='ordinary',source_cell='src')}
        p=planner.build(i);self.assertFalse(p['keep']);self.assertIn('incomplete_mux_macro',p['decisions'][0]['status'])
    def test_upstream_budget_rejects(self):
        i=self.inventory();i.loads['src/Q']=99;i.loads['a/O']=99
        self.assertFalse(planner.build(i)['keep'])
    def test_control_margin_rejects(self):
        i=self.inventory();i.edges['ff']['CE']=dict(key='src/Q',kind='ordinary',source_cell='src')
        i.slacks['ff/CE']=dict(max='.1',min='.1',requirement='6.7')
        p=planner.build(i);self.assertFalse(p['keep']);self.assertEqual(p['decisions'][0]['status'],'control_input_margin:CE')
    def test_clock_exception_rejected(self):
        i=self.inventory();i.slacks['ff/D']['requirement']='13.4'
        self.assertFalse(planner.build(i)['keep'])
    def test_bounds_reject(self):
        self.assertFalse(planner.build(self.inventory(),max_added=0)['keep'])
    def test_exclusion_is_stable(self):
        self.assertFalse(planner.build(self.inventory(),excluded=['ff/Q@SLR0'])['keep'])
    def test_all_input_branches_count(self):
        i=self.inventory();i.cells['bad']=dict(name='bad',ref='FDRE',slr='SLR1',x=2,y=5,period=6.7)
        i.edges['b']['I1']=dict(key='bad/Q',kind='ordinary',source_cell='bad');i.loads['bad/Q']=1
        p=planner.build(i);self.assertFalse(p['keep'])
    def test_gate_rejects_positive_to_negative_and_missing(self):
        before={('ff/D','max'):.4,('ff/D','min'):.1};after={('ff/D','max'):.3,('ff/D','min'):.1,('copy/D','max'):-.2}
        mapping=[dict(pin='copy/D',original='ff/D',owner='one')]
        stats=dict(wns=.3,tns=0,whs=.1,ths=0)
        p=gate.evaluate(before,after,mapping,stats,stats,dict(keep=['one','two'],owners={'one':['shared'],'two':['shared']}))
        self.assertFalse(p['accepted']);self.assertEqual(p['reject_ids'],['one','two'])
    def test_tcl_serialization_names_are_literal(self):
        value={'cell[12]/O@SLR0':{'net':'a $b [c] " d\\e'}}
        script='set x '+planner.word(planner.tcl(value))+'\nputs [dict get $x {cell[12]/O@SLR0} net]\n'
        p=subprocess.run(['tclsh'],input=script,text=True,capture_output=True,check=True)
        self.assertEqual(p.stdout.strip(),'a $b [c] " d\\e')
    def test_control_alias_uses_new_source_and_original_reference_and_final_link(self):
        i=self.inventory()
        i.cells['ce_old']=dict(name='ce_old',ref='FDRE',slr='SLR1',x=5,y=6,period=6.7)
        i.cells['ce_local']=dict(name='ce_local',ref='FDRE',slr='SLR0',x=3,y=2,period=6.7)
        i.edges['ff']['CE']=dict(key='ce_old/Q',kind='ordinary',source_cell='ce_old')
        i.slacks['ff/CE']=dict(max='.3',min='.1',requirement='6.7')
        i.loads.update({'ce_old/Q':1,'ce_local/Q':1})
        row=i.candidates[0];row['control_drivers']={'CE':'ce_local/Q'}
        old_source=planner.pos(i.cells['ce_old']);new_source=planner.pos(i.cells['ce_local'])
        old_ff=planner.pos(i.cells['ff']);new_ff=('SLR0',2.0,2.0)
        self.assertAlmostEqual(.3-(planner.wire(new_source,new_ff)-planner.wire(old_source,old_ff)),.62)
        with patch.object(planner,'wire',wraps=planner.wire) as observed:
            result=planner.build(i)
        self.assertEqual(result['keep'],[row['id']])
        self.assertEqual(result['links'][row['replica']+'/CE'],'ce_local/Q')
        observed.assert_any_call(new_source,new_ff)
        observed.assert_any_call(old_source,old_ff)
        # The same FF placement using the original, remote CE must fail.  Output
        # benefit cannot hide that control-input cost.
        del row['control_drivers']
        remote=planner.build(i)
        self.assertFalse(remote['keep'])
        self.assertEqual(remote['decisions'][0]['status'],'control_input_margin:CE')

    def test_detached_loads_are_actual_root_budget_and_cannot_be_negative(self):
        i=self.inventory();row=i.candidates[0]
        i.loads['ff/Q']=99
        i.edges['ff']['CE']=dict(key='ff/Q',kind='ordinary',source_cell='ff')
        i.slacks['ff/CE']=dict(max='3',min='.1',requirement='6.7')
        row['loads']='16';row['detached_loads']=0
        # A retained original identity-tree branch is not detached just because
        # 16 functional descendants are served by a new copy.  The CE adds the
        # 100th real input to the original root, which must be rejected.
        result=planner.build(i)
        self.assertFalse(result['keep'])
        self.assertEqual(result['decisions'][0]['status'],'shared_fanout_or_resource_budget')
        row['detached_loads']=1
        self.assertEqual(planner.build(i)['keep'],[row['id']])
        for invalid in [-1,5]:
            with self.subTest(detached=invalid):
                bad=self.inventory();bad.loads['ff/Q']=4
                bad.candidates[0]['detached_loads']=invalid
                result=planner.build(bad)
                self.assertFalse(result['keep'])
                self.assertEqual(result['decisions'][0]['status'],'invalid_detached_loads')

    def test_absent_new_fields_preserve_existing_planning_behavior(self):
        old=self.inventory();explicit=copy.deepcopy(old)
        explicit.candidates[0]['control_drivers']={}
        explicit.candidates[0]['detached_loads']=explicit.candidates[0]['loads']
        baseline=planner.build(old)
        self.assertEqual(baseline,planner.build(explicit))
        self.assertEqual(baseline['keep'],['ff/Q@SLR0'])
        self.assertEqual(len(baseline['aux']),1)
        self.assertEqual(baseline['estimates']['ff/Q@SLR0']['mode'],'target_local')
        self.assertEqual(baseline['links']['sbeco_local_ff_1_SLR0/CE'],'ONE')


if __name__=='__main__':unittest.main()
