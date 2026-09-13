import pathlib,json,shutil,hashlib,subprocess
b=pathlib.Path(__file__).resolve().parent
m=json.loads((b/'manifest.json').read_text()); c=m['cases'][0]
prior=pathlib.Path(m['synth_provenance'])
assert (prior/'implementation_exit_code.txt').read_text().strip()=='1'
source=pathlib.Path(m['synth_source']);assert source.is_file()
run=pathlib.Path(c['run']);run.mkdir();inp=run/'inputs';inp.mkdir()
for f in b.iterdir():
 if f.suffix in {'.tcl','.sh','.cpp','.xdc'}:shutil.copy2(f,inp/f.name)
shutil.copy2(source,run/'post_synth.dcp')
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for block in iter(lambda:f.read(1048576),b''):h.update(block)
 return h.hexdigest()
h=sha(source);assert sha(run/'post_synth.dcp')==h
(run/'synth_provenance.json').write_text(json.dumps({'source':str(source),'sha256':h,'copy_verified':True},indent=2)+'\n')
(run/'input_hashes.json').write_text(json.dumps({f.name:sha(f) for f in inp.iterdir() if f.is_file()},indent=2)+'\n')
subprocess.run(['tmux','new-session','-d','-s',c['session'],f'env RUN_DIR={run} bash {inp}/launch.sh'],check=True)
print(c['session'])
