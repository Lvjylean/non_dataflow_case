import pathlib,json,shutil,hashlib,subprocess
b=pathlib.Path(__file__).resolve().parent
m=json.loads((b/'manifest.json').read_text()); c=m['cases'][0]
prior=pathlib.Path(m['hls_provenance'])
assert (prior/'hls_exit_code.txt').read_text().strip()=='0'
assert (prior/'implementation_exit_code.txt').read_text().strip()=='1'
assert (b/'clock.xdc').is_file()
run=pathlib.Path(c['run']);run.mkdir();inp=run/'inputs';inp.mkdir()
for f in b.iterdir():
 if f.suffix in {'.tcl','.sh','.cpp','.xdc'}:shutil.copy2(f,inp/f.name)
shutil.copytree(m['rtl_source'],run/'rtl')
source=pathlib.Path(m['rtl_source'])
for f in source.rglob('*'):
 if f.is_file():
  assert hashlib.sha256(f.read_bytes()).digest()==hashlib.sha256((run/'rtl'/f.relative_to(source)).read_bytes()).digest()
(run/'rtl_provenance.json').write_text(json.dumps({'source':str(source),'hash_verified':True,'hls_source':str(prior)},indent=2)+'\n')
h={str(f.relative_to(run)):hashlib.sha256(f.read_bytes()).hexdigest() for d in ['inputs','rtl'] for f in (run/d).rglob('*') if f.is_file()}
(run/'input_hashes.json').write_text(json.dumps(h,indent=2)+'\n')
subprocess.run(['tmux','new-session','-d','-s',c['session'],f'env RUN_DIR={run} bash {inp}/launch.sh'],check=True)
print(c['session'])
