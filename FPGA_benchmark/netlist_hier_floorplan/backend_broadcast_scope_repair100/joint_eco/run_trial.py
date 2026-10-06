from pathlib import Path
import hashlib,json,os,subprocess,sys,time,traceback
root=Path(sys.argv[1]).resolve();name=sys.argv[2] if len(sys.argv)>2 else 'trial01'
assert name.startswith('trial') and name.isalnum()
codedir=Path(__file__).resolve().parent
config_path=Path(sys.argv[3]).resolve() if len(sys.argv)>3 else root/'run_config.json'
config=json.loads(config_path.read_text());trial=root/name;trial.mkdir()
state=dict(status='RUNNING',stage='preflight',started=time.time(),controller_pid=os.getpid(),stages=[])
def save():
    state['updated']=time.time();p=trial/'status.json';t=p.with_suffix('.tmp');t.write_text(json.dumps(state,indent=2)+'\n');t.replace(p)
def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(8*1024*1024),b''):h.update(chunk)
    return h.hexdigest()
def run(mode):
    out=trial/('implementation' if mode=='implement' else 'reopened')
    impl=trial/'implementation'
    cmd=['/home/lduac/Software/Xilinx/Vivado/2023.2/bin/vivado','-mode','batch','-source',str(codedir/'run.tcl'),'-log',str(trial/(mode+'.log')),'-journal',str(trial/(mode+'.jou')),'-tclargs',str(root),config['input'] if mode=='implement' else str(impl/'post_route.dcp'),config['plan'] if mode=='implement' else str(impl/'plan.tcl'),config['prior_certificate'],str(root/config['selection']/'spec.tcl'),str(out),mode,str(impl/'certificate.tcl')]
    tick=time.time()
    with (trial/(mode+'_console.log')).open('xb') as log:
        p=subprocess.Popen(cmd,cwd=trial,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT)
        state.update(stage=mode,active_pid=p.pid,command=cmd);save();rc=p.wait()
    state['stages'].append(dict(name=mode,seconds=time.time()-tick,returncode=rc));state['active_pid']=None;save()
    if rc:raise RuntimeError(mode+' failed; logs retained, no blind retry')
try:
    save()
    assert (root/config['validation_pass']).exists(),'Native validation is required'
    physical_validation=json.loads(Path(config['physical_validation_json']).read_text())
    assert physical_validation.get('status')=='PASS' and physical_validation.get('native_physical_eco_pass'), 'Native physical ECO validation is required'
    physical_sources=physical_validation.get('source_hashes', {})
    for rel in ['physical_eco.tcl', 'joint_eco/run.tcl', 'joint_eco/run_trial.py']:
        assert rel in physical_sources and digest(codedir.parent/rel)==physical_sources[rel], 'Untested physical ECO source: '+rel
    for rel,want in json.loads((root/config['validation_source_manifest']).read_text()).items():assert digest(root/rel)==want,'Native-tested code changed: '+rel
    assert digest(config['input'])==config['sha256'],'Input DCP changed'
    for rel,want in config['source_sha256'].items():assert digest(root/rel)==want,'Source changed: '+rel
    (trial/'input.json').write_text(json.dumps(config,indent=2)+'\n')
    state.update(stage='MEMORY_ADMISSION');save()
    subprocess.run(['python3',str(codedir/'memory_gate.py'),str(root),str(trial),'prepare',str(os.getpid())],check=True)
    run('implement')
    if (trial/'implementation/REJECTED_BEFORE_ROUTE').exists():
        state.update(status='CANDIDATE_REJECTED',stage='REPORT',ended=time.time());save()
    else:
        run('reopen');state.update(status='IMPLEMENTED_REOPENED',stage='REPORT');save()
    subprocess.run(['python3',str(codedir/'report_trial.py'),str(trial)],check=True)
    state.update(status=json.loads((trial/'result.json').read_text())['status'],stage='COMPLETE',ended=time.time());save()
except Exception:
    state.update(status='ERROR',error=traceback.format_exc(),ended=time.time());save();raise
