import pathlib,json,shutil,hashlib,subprocess
b=pathlib.Path(__file__).resolve().parent;m=json.loads((b/'manifest.json').read_text());c=m['cases'][0];run=pathlib.Path(c['run']);run.mkdir();inp=run/'inputs';inp.mkdir()
for f in b.iterdir():
 if f.suffix in {'.tcl','.sh','.cpp'}:shutil.copy2(f,inp/f.name)
shutil.copytree(b/'sources',run/'sources');shutil.copytree(m['library_source'],run/'library')
h={str(f.relative_to(run)):hashlib.sha256(f.read_bytes()).hexdigest() for d in ['inputs','sources','library'] for f in (run/d).rglob('*') if f.is_file()};(run/'input_hashes.json').write_text(json.dumps(h,indent=2)+'\n')
subprocess.run(['tmux','new-session','-d','-s',c['session'],f'env RUN_DIR={run} bash {inp}/launch.sh'],check=True);print(c['session'])
