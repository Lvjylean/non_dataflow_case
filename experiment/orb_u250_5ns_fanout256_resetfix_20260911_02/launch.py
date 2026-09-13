import pathlib,json,shutil,subprocess,hashlib
batch=pathlib.Path(__file__).resolve().parent
m=json.loads((batch/'manifest.json').read_text())
for c in m['cases']:
 run=pathlib.Path(c['run']);run.mkdir();inp=run/'inputs';inp.mkdir()
 for f in batch.iterdir():
  if f.suffix in {'.tcl','.sh'}:shutil.copy2(f,inp/f.name)
 (run/'baseline.txt').write_text(c['baseline_run']+'\n')
 (run/'input_hashes.json').write_text(json.dumps({f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in inp.iterdir()},indent=2)+'\n')
 command=f"env RUN_DIR={run} BASELINE_DIR={c['baseline_run']} BATCH_DIR={m['lock_directory']} bash {inp}/queue.sh"
 subprocess.run(['tmux','new-session','-d','-s',c['session'],command],check=True)
 print(c['session'],flush=True)
