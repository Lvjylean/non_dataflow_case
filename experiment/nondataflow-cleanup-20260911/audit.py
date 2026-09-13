#!/usr/bin/env python3
"""Verify retained case RTL against its pre-migration batch hash inventory."""
from pathlib import Path
import json,hashlib,sys,re
p=Path(sys.argv[1]).resolve();r=json.loads((p/'case.json').read_text())
d=p/'hls/sol/syn/verilog';top=d/(r['top']+'.v');assert re.search(r'\bmodule\s+'+re.escape(r['top'])+r'\b',top.read_text())
old=json.loads((p.parent/'.history/nondataflow-batches'/r['original_batch']/'rtl_audit.json').read_text())
record=next(x for x in old['results'] if x['id']==r['id'])
files={str(f.relative_to(d)):{'bytes':f.stat().st_size,'sha256':hashlib.sha256(f.read_bytes()).hexdigest()} for f in d.rglob('*') if f.is_file()}
assert files==record['files'],r['id']
assert hashlib.sha256((p/'sources/kernel.cpp').read_bytes()).hexdigest()==r['source_sha256']
(p/'rtl_audit.json').write_text(json.dumps({'original_batch':r['original_batch'],'unchanged':True,'files':files},indent=2))
print(p.name,'PASS',len(files),'unchanged RTL/IP files')
