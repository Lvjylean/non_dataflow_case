import pathlib,json,shutil,subprocess,os,hashlib
batch=pathlib.Path(__file__).resolve().parent
manifest=json.loads((batch/'manifest.json').read_text())
for c in manifest['cases']:
    run=pathlib.Path(c['run']); run.mkdir()
    inp=run/'inputs'; inp.mkdir()
    for f in batch.iterdir():
        if f.suffix in {'.tcl','.sh','.xdc'}: shutil.copy2(f,inp/f.name)
    shutil.copytree(pathlib.Path(c['case'])/'hls/sol/syn/verilog',run/'rtl')
    hashes={str(f.relative_to(run)):hashlib.sha256(f.read_bytes()).hexdigest() for d in ['inputs','rtl'] for f in (run/d).rglob('*') if f.is_file()}
    (run/'input_hashes.json').write_text(json.dumps(hashes,indent=2)+'\n')
    env=os.environ.copy();env.update(RUN_DIR=str(run),BATCH_DIR=str(batch))
    command=f'env RUN_DIR={run} BATCH_DIR={batch} bash {inp}/queue.sh'
    subprocess.run(['tmux','new-session','-d','-s',c['session'],command],check=True,env=env)
    print(c['session'],str(run),flush=True)
