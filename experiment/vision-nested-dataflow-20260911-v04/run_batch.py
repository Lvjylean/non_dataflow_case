from pathlib import Path
import os,json,subprocess,time,concurrent.futures,xml.etree.ElementTree as ET
root=Path(__file__).resolve().parent;caps={'LUT':432000,'FF':864000,'DSP':3072,'BRAM_18K':1344,'URAM':320}
def run(job):
 d=root/'runs'/job['name'];d.mkdir(parents=True);src=root/'cases'/job['name']
 tcl=f'''open_project hls
set_top {job['top']}
add_files {{{src/job['cpp']}}} -cflags {{-std=c++14 -I{src} -I{root/'vision/L1/include'}}}
open_solution sol -flow_target vivado
set_part {{xcu250-figd2104-2L-e}}
create_clock -period 5
csynth_design
exit
'''
 (d/'run.tcl').write_text(tcl);r=dict(job,status='RUNNING',started=time.time(),server_path=str(d));(d/'status.json').write_text(json.dumps(r,indent=2))
 with (d/'hls.log').open('w') as out:
  p=subprocess.run(['/usr/bin/time','-v','-o','time.txt','timeout','--kill-after=30s','1800','vitis_hls','-f','run.tcl'],cwd=d,stdout=out,stderr=subprocess.STDOUT)
 r.update(returncode=p.returncode,seconds=round(time.time()-r['started'],2),status='COMPLETE' if p.returncode==0 else 'TIMED_OUT' if p.returncode in [124,137] else 'FAILED')
 x=d/'hls/sol/syn/report'/str(job['top']+'_csynth.xml')
 if p.returncode==0 and x.exists():
  t=ET.parse(x);res={k:int(t.findtext('.//AreaEstimates/Resources/'+k) or 0) for k in caps};eq={k:res[k]/caps[k] for k in caps};peak=max(eq,key=eq.get)
  children=[]
  for q in x.parent.glob('*_csynth.xml'):
   tq=ET.parse(q);kind=tq.findtext('.//PerformanceEstimates/PipelineType')
   if kind and 'dataflow' in kind.lower():children.append({'report':q.name,'pipeline_type':kind})
  r.update(resources=res,slr_ratios=eq,size_resource=peak,size_slr_ratio=eq[peak],top_pipeline_type=t.findtext('.//PerformanceEstimates/PipelineType'),dataflow_reports=children)
  r['lut_in_range']=108000<=res['LUT']<=864000;r['all_resources_fit_device']=all(v<=4 for v in eq.values())
 (d/'status.json').write_text(json.dumps(r,indent=2));return r
jobs=json.loads((root/'jobs.json').read_text())
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
 results=[]
 for r in pool.map(run,jobs):results.append(r);(root/'results.json').write_text(json.dumps(results,indent=2))
(root/'complete.txt').write_text('done\n')
