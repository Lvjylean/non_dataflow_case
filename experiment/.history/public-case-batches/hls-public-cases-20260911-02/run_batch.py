from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import subprocess,json,time,datetime
ROOT=Path(__file__).resolve().parent
jobs=json.loads((ROOT/'jobs.json').read_text())
def run(job):
    d=ROOT/'runs'/job['id']
    state=dict(job,status='RUNNING',started=datetime.datetime.now(datetime.timezone.utc).isoformat(),server_path=str(d))
    def save(): (d/'status.json').write_text(json.dumps(state,indent=2)+'\n')
    save(); start=time.monotonic()
    with (d/'run.log').open('w') as log:
        p=subprocess.run(['/usr/bin/time','-v','vitis_hls','-f','run.tcl'],cwd=d,stdout=log,stderr=subprocess.STDOUT)
    rtl=list((d/'hls/sol/syn/verilog').glob('*.v'))
    xml=d/'hls/sol/syn/report'/f"{job['top']}_csynth.xml"
    state.update(status='COMPLETE' if p.returncode==0 and rtl and xml.exists() else 'FAILED',returncode=p.returncode,elapsed_seconds=time.monotonic()-start,rtl_files=len(rtl))
    save();print(job['id'],state['status'],flush=True)
with ThreadPoolExecutor(max_workers=3) as pool:list(pool.map(run,jobs))
(ROOT/'finished.json').write_text(json.dumps({'finished':datetime.datetime.now(datetime.timezone.utc).isoformat()}))
