import copy,unittest
from planner import Inventory,build,tcl
from gates import evaluate
from collections import defaultdict
class JointTests(unittest.TestCase):
    def fixture(self):
        i=Inventory.__new__(Inventory);i.inputs=defaultdict(dict)
        i.cells={n:dict(name=n,ref=r,init="2'h2" if r=='LUT1' else '',slr=s,cr='X0Y0',x='0',y='0',loc='') for n,r,s in [('src','FDRE','SLR1'),('a','LUT1','SLR0'),('b','LUT1','SLR1'),('ff','FDRE','SLR0'),('original','FDRE','SLR1')]}
        i.inputs['a']={'I0':('driver','src/Q')};i.inputs['b']={'I0':('driver','a/O')}
        i.loads={'src/Q':['a/I0'],'a/O':['b/I0'],'b/O':['ff/D','original/D']}
        i.targets=[dict(endpoint='ff/D',original='ap_CS_fsm_reg[1]',slack='-.4',driver='b/O',slr='SLR0',status='supported',cone_cells='a|b')]
        return i
    def test_pingpong_and_original(self):
        i=self.fixture();s=build(i)
        self.assertEqual(len(s['targets']),1);self.assertEqual(s['changes']['ff/D'][0],'b/O');self.assertNotIn('original/D',s['changes'])
        self.assertTrue(all(v['config']['ref'].startswith('LUT') for v in s['clones'].values()))
        self.assertLess(s['decisions'][0]['crossings_after'],s['decisions'][0]['crossings_before'])
    def test_incomplete_macro_rejected(self):
        i=self.fixture();i.cells['b']['ref']='MUXF7'
        i.inputs['b']={'I0':('driver','a/O'),'I1':('driver','src/Q'),'S':('driver','src/Q')}
        with self.assertRaisesRegex(ValueError,'No safe'):build(i)
    def test_high_fanout_ff_rejected(self):
        i=self.fixture();i.loads['src/Q']=[f'x{k}/D' for k in range(99)];i.cells['a']['slr']='SLR1'
        with self.assertRaisesRegex(ValueError,'overbudget_non_LUT'):build(i)
    def test_parallel_lut_split(self):
        i=self.fixture();i.cells['a']['slr']='SLR0';i.loads['a/O']=[f'x{k}/D' for k in range(99)]
        i.loads['a/O'][0]='b/I0'
        s=build(i);self.assertTrue(any(n.startswith('jcone_helper') for n in s['clones']));self.assertLess(max(s['projected'].values()),100)
    def test_timing_rejects_original_regression(self):
        base={'wns':-.4,'tns':-20,'whs':.01};new={'wns':-.2,'tns':-10,'whs':.01}
        a={('copy/D','max'):-.4,('original/D','max'):.2};b={('copy/D','max'):-.1,('original/D','max'):-.001}
        self.assertFalse(evaluate(a,b,base,new,set())['accepted'])
    def test_old_positive_baseline_remains_binding(self):
        base={'wns':-.4,'tns':-20,'whs':.01};new={'wns':-.2,'tns':-10,'whs':.01}
        self.assertFalse(evaluate({('original/D','max'):-.09},{('original/D','max'):-.01},base,new,{'original/D'})['accepted'])
    def test_missing_guard_fails(self):
        sta={'wns':.1,'tns':0,'whs':.01}
        self.assertFalse(evaluate({('original/D','max'):.2},{},sta,sta,set())['accepted'])
    def test_accepts_improvement(self):
        a={'wns':-.4,'tns':-20,'whs':.01};b={'wns':-.2,'tns':-10,'whs':.01}
        self.assertTrue(evaluate({('copy/D','max'):-.4},{('copy/D','max'):-.2},a,b,set())['accepted'])
if __name__=='__main__':unittest.main()
