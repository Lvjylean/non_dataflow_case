"""User-authorized cleanup and case-based migration, with content verification."""
import argparse,hashlib,json,os,shutil
from pathlib import Path
ap=argparse.ArgumentParser();ap.add_argument('--server',action='store_true');ap.add_argument('--apply',action='store_true');ap.add_argument('--plan',required=True);a=ap.parse_args()
plan=json.loads(Path(a.plan).read_text())
ws=Path('/Projects/jinyang/workspace/non_dataflow_crossSLR') if a.server else Path.cwd()
remote=Path('/Projects/jinyang/workspace/non_dataflow_crossSLR/case/experiment')
roots=[ws/'case/experiment'] if a.server else [ws/'experiment_inputs',ws/'reports']
batches=sorted({r['batch'] for r in plan['keep']+plan['delete']})
validations=['hls-nondataflow-validation-20260911','hls-nondataflow-validation-20260911-02']
def digest(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
def hashes(d):return {str(p.relative_to(d)):digest(p) for p in d.rglob('*') if p.is_file()}
def writejson(p,v):p.write_text(json.dumps(v,indent=2)+'\n')
# Refuse to migrate any directory used as a live process working directory.
if a.server:
 old=[remote/n for n in batches+validations]
 for proc in Path('/proc').glob('[0-9]*'):
  try:
   cwd=(proc/'cwd').resolve();assert not any(cwd==d or d in cwd.parents for d in old),(proc,cwd)
  except (FileNotFoundError,PermissionError,ProcessLookupError):pass
for root in roots:
 for r in plan['keep']:
  assert (root/r['batch']).is_dir()
  assert not (root/r['new_name']).exists(),root/r['new_name']
print(json.dumps({'apply':a.apply,'roots':[str(p) for p in roots],'keep':len(plan['keep']),'delete':[{k:r.get(k) for k in ['id','status','classification']} for r in plan['delete']]}))
if not a.apply:raise SystemExit
records=[]
for root in roots:
 isinputs=not a.server and root.name=='experiment_inputs'
 for r in plan['keep']:
  batch=root/r['batch'];dest=root/r['new_name'];oldrun=batch/'runs'/r['id']
  before=hashes(oldrun) if oldrun.exists() else {}
  if oldrun.exists():shutil.move(str(oldrun),dest)
  else:dest.mkdir()
  if a.server or isinputs:
   shutil.copytree(batch/'library',dest/'library')
   assert hashes(batch/'library')==hashes(dest/'library')
   (dest/'sources').mkdir(exist_ok=True)
   shutil.copy2(batch/r['source'],dest/'sources/kernel.cpp')
   assert digest(dest/'sources/kernel.cpp')==r['source_sha256']
  newremote=str(remote/r['new_name']);oldremote=str(remote/r['batch'])
  mapping={str(remote/r['batch']/'runs'/r['id']):newremote,str(remote/r['batch']/r['source']):newremote+'/sources/kernel.cpp',oldremote+'/library':newremote+'/library'}
  validation=None
  for vn in validations:
   vd=root/vn/r['id']
   # Validation outcomes are taken from the synchronized evidence, not folder names.
   evidence_root=remote if a.server else ws/'reports'
   results=evidence_root/vn/'results.json'
   rows=json.loads(results.read_text()) if results.exists() else []
   passed=next((v for v in rows if v['id']==r['id'] and v['status']=='PASS'),None)
   if not passed:continue
   validation=passed
   if vd.exists():
    before.update({'validation/'+k:v for k,v in hashes(vd).items()})
    shutil.move(str(vd),dest/'validation')
   else:(dest/'validation').mkdir(exist_ok=True)
   tb=root/vn/'tb.cpp'
   if tb.exists():shutil.copy2(tb,dest/'validation/tb.cpp')
   mapping[str(remote/vn/r['id'])]=newremote+'/validation'
   mapping[str(remote/vn/'tb.cpp')]=newremote+'/validation/tb.cpp'
  changed=[]
  for p in dest.rglob('*'):
   if not p.is_file() or p.suffix not in {'.tcl','.app','.aps','.sh','.json'}:continue
   s=p.read_text(errors='surrogateescape');t=s
   for x,y in sorted(mapping.items(),key=lambda v:-len(v[0])):t=t.replace(x,y)
   if t!=s:p.write_text(t,errors='surrogateescape');changed.append(str(p.relative_to(dest)))
  for rel,h in before.items():
   if rel not in changed:assert digest(dest/rel)==h,(dest,rel)
  row=dict(r);row.pop('new_name',None);row['directory']=r['new_name'];row['original_server_path']=r['server_path'];row['server_path']=newremote;row['source']='sources/kernel.cpp';row['verilog_directory']=newremote+'/hls/sol/syn/verilog';row['validation']=validation
  row['original_batch']=row.pop('batch');row['original_source']=r['source'];writejson(dest/'case.json',row)
  if a.server or isinputs:
   # Explicit fresh output directory prevents accidental overwriting of success.
   flags='-std=c++14 '+' '.join('-I'+newremote+'/library/'+x for x in ['solver/L2/include','solver/L1/include','security/L1/include'])
   tcl=f'''if {{![info exists ::env(HLS_OUTPUT_DIR)]}} {{error "Set HLS_OUTPUT_DIR to a new absolute directory"}}
set output $::env(HLS_OUTPUT_DIR)
if {{[file pathtype $output] ne "absolute" || [file exists $output]}} {{error "Output must be new and absolute"}}
open_project $output
set_top {r['top']}
add_files {{{newremote}/sources/kernel.cpp}} -cflags {{{flags}}}
open_solution sol -flow_target vivado
set_part {{xcu250-figd2104-2L-e}}
create_clock -period 5.0 -name default
csynth_design
exit
'''
   (dest/'rerun.tcl').write_text(tcl)
   (dest/'launch.sh').write_text('#!/usr/bin/env bash\nset -eo pipefail\n: "${HLS_OUTPUT_DIR:?Set a fresh absolute HLS output directory}"\nsource /home/lduac/Software/Xilinx/Vitis_HLS/2023.2/settings64.sh\nvitis_hls -f "'+newremote+'/rerun.tcl"\n')
  records.append({'root':str(root),'directory':r['new_name'],'verified_unchanged_files':len(before)-len([c for c in changed if c in before]),'updated_metadata':changed})
 # Keep compact historical metadata only; remove abandoned experiment trees.
 hist=root/'.history/nondataflow-batches';hist.mkdir(parents=True,exist_ok=True)
 for name in batches+validations:
  b=root/name
  if not b.exists():continue
  hd=hist/name;hd.mkdir()
  for fn in ['manifest.json','results.json','input_hashes.json','rtl_audit.json','summary.md','EXPERIMENT.md','status.json']:
   if (b/fn).is_file():shutil.copy2(b/fn,hd/fn)
  shutil.rmtree(b)
writejson(ws/'case/experiment/nondataflow-cleanup-audit.json' if a.server else ws/'reports/nondataflow-cleanup-local.json',{'retained':records,'deleted_configurations':plan['delete'],'all_retained_payloads_verified':True})
