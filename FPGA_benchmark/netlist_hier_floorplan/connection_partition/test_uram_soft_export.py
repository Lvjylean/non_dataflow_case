"""Resource envelopes preserve the original core, membership and other grids."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from uram_soft_export import build,sha


class ExportTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);self.old=self.root/'old';(self.old/'export').mkdir(parents=True)
        self.device=self.root/'cr.tsv'
        self.device.write_text('cr\tx\ty\tslr\tURAM\n'+''.join(f'X{x}Y{y}\t{x}\t{y}\tSLR{y//4}\t{16 if x==1 else 0}\n' for x in range(3) for y in range(5)))
        self.core=dict(regions={mid:dict(bounds=[0,y,2,y],crs=[f'X{x}Y{y}' for x in range(3)],capacity=dict(URAM=16)) for mid,y in [('S02',3),('S14',2)]},components=dict(J=123),objective=123,overlap=dict(valid=True))
        self.soft=copy.deepcopy(self.core);self.soft['planning_regions']=copy.deepcopy(self.core['regions']);self.soft['resource_accounting']=dict(schema='core-only-v1')
        self.soft['regions']['S14']['crs'].append('X0Y1')
        (self.old/'core_solution.json').write_text(json.dumps(self.core))
        (self.old/'export/static_regions.json').write_text(json.dumps(self.soft))
        (self.old/'export/modules.json').write_text(json.dumps(dict(modules=[dict(module_id=m,URAM=16) for m in ['S02','S14']])))
        (self.old/'membership.tsv').write_text('frozen membership\n')
        (self.old/'regions.tcl').write_text('set planned_regions {}\n')
        (self.old/'soft_region_adapter.tcl').write_text('proc bi_apply {out} {\n    if {[bi_geometry $out/geometry_initial 1]} {error bad}\n}\n')
        self.bind()

    def bind(self):
        (self.old/'manifest.json').write_text(json.dumps(dict(status='PASS',files={str(p.relative_to(self.old)):sha(p) for p in self.old.rglob('*') if p.is_file() and p.name!='manifest.json'})))

    def test_case_envelopes_and_all_original_accounting_are_preserved(self):
        out=self.root/'new';oldhash=sha(self.old/'core_solution.json')
        additions=build(self.old,out,self.device,dict(S02=[0,3,2,4],S14=[0,0,2,2]))
        self.assertEqual(additions['S02']['URAM']['added_crs'],['X1Y4'])
        self.assertEqual(additions['S14']['URAM']['added_crs'],['X1Y0','X1Y1'])
        self.assertEqual(additions['S02']['URAM']['allowed_site_count'],32)
        self.assertEqual(additions['S14']['URAM']['allowed_site_count'],48)
        self.assertEqual(len(additions['S14']['URAM']['envelope_crs']),9)
        new=json.loads((out/'export/static_regions.json').read_text())
        for key,value in self.soft.items():self.assertEqual(new[key],value)
        self.assertEqual(sha(out/'core_solution.json'),oldhash)
        self.assertEqual(sha(out/'membership.tsv'),sha(self.old/'membership.tsv'))
        for n,h in json.loads((out/'manifest.json').read_text())['files'].items():self.assertEqual(sha(out/n),h)

    def test_rejects_horizontal_expansion(self):
        with self.assertRaisesRegex(ValueError,'vertical'):build(self.old,self.root/'new',self.device,dict(S02=[0,3,1,4]))

    def test_rejects_non_full_module(self):
        meta=json.loads((self.old/'export/modules.json').read_text());meta['modules'][0]['URAM']=15
        (self.old/'export/modules.json').write_text(json.dumps(meta));self.bind()
        with self.assertRaisesRegex(ValueError,'100%'):build(self.old,self.root/'new',self.device,dict(S02=[0,3,2,4]))

    def test_rejects_repeat_and_changed_source(self):
        (self.old/'membership.tsv').write_text('changed')
        with self.assertRaisesRegex(ValueError,'binding mismatch'):build(self.old,self.root/'new',self.device,dict(S02=[0,3,2,4]))

    @unittest.skipUnless(shutil.which('tclsh'),'tclsh unavailable')
    def test_reloading_legacy_input_clears_resource_extras(self):
        for name,extra in [('extended','set ::bi_resource_extra_crs [dict create S02 [dict create URAM {X1Y4}]]\n'),('legacy','')]:
            p=self.root/name;p.mkdir()
            (p/'regions.tcl').write_text('set planned_regions [dict create S02 {X1Y3}]\nset planned_bounds [dict create S02 {1 3 1 3}]\n'+extra)
            (p/'membership.tsv').write_text('name\tmodule\tresource\tref\nu0\tS02\tURAM\tURAM288\n')
        adapter=Path(__file__).resolve().parent.parent/'balanced_implementation/adapter.tcl'
        script='source {'+str(adapter)+'}\nbi_load {'+str(self.root/'extended')+'}\n'
        script+='if {![dict exists $::bi_resource_extra_crs S02 URAM]} {error "missing extension"}\n'
        script+='bi_load {'+str(self.root/'legacy')+'}\n'
        script+='if {[dict size $::bi_resource_extra_crs]} {error "stale extension"}\nputs PASS\n'
        result=subprocess.run(['tclsh'],input=script,text=True,capture_output=True,check=True)
        self.assertEqual(result.stderr,'');self.assertEqual(result.stdout.strip(),'PASS')


if __name__=='__main__':unittest.main()
