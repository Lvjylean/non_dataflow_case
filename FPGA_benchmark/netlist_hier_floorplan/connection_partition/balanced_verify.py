"""Read back all delivered files against the immutable reference before packaging."""
import argparse
import csv
import gzip
import hashlib
import json
import pickle
import tarfile
from collections import Counter
from pathlib import Path

import partition as base
from improve import digest, labels_for
from static_regions import load_device, overlap_audit


def main(run):
    binding=json.loads((run/'binding.json').read_text())
    assert digest(run/'graph.pkl')==binding['graph_sha256']
    assert digest(binding['input_dcp'])==binding['input_sha256']
    assert digest(run/'cr.tsv')==binding['device_sha256']
    assert digest(run/'source/balanced_config.json')==binding['config_sha256']
    with (run/'graph.pkl').open('rb') as f:data=pickle.load(f)
    device=load_device(run/'cr.tsv')
    folders=['selected']+[a['directory'] for a in json.loads((run/'alternatives.json').read_text())]
    checks=[]
    for folder in folders:
        directory=run/folder;s=json.loads((directory/'modules.json').read_text())
        regions=json.loads((directory/'static_regions.json').read_text())
        groups=json.loads((run/'candidates'/s['selected_candidate']/'groups.json').read_text())
        labels=labels_for(data,groups)
        mapping={int(m['candidate_module_id'][1:]):m['module_id'] for m in s['modules']}
        counts=Counter();resources=Counter();n=0
        with gzip.open(directory/'leaf_cells.tsv.gz','rt') as f:
            for n,row in enumerate(csv.DictReader(f,delimiter='\t'),1):
                reference=data['cells'][n-1]
                for key in ('cell_id','cell_name','primitive','original_hierarchy'):
                    assert row[key]==reference[key],(folder,n,key)
                assert row['cell_id']==f'c{n-1}'
                demand=base.resources(row['primitive'])
                assert all(int(row[r])==demand.get(r,0) for r in base.RESOURCES)
                expected=base.infrastructure(row['primitive'])
                if expected is None:expected=mapping[labels[data['atom_of'][n-1]]]
                assert row['module_id']==expected
                counts[expected]+=1;resources.update(demand)
        assert n==len(data['cells'])
        for m in s['modules']:
            assert counts[m['module_id']]==m['cells']
            assert m['floorplan_eligible']
        assert all(resources[r]==data['totals'].get(r,0) for r in base.RESOURCES)
        audit=overlap_audit(s['modules'],regions['regions'],device)
        assert audit['valid'] and audit['maximum_utilization']==regions['overlap']['maximum_utilization']
        checks.append(dict(directory=folder,candidate=s['selected_candidate'],cells=n,
            modules=len(s['modules']),unique_ordered_ids=True,attributes_match_input=True,
            atom_membership_matches=True,resource_totals_match=True,resource_regions_valid=True,
            ownership=dict(counts)))
    main_name=json.loads((run/'selection.json').read_text())['selected']
    repaired=run/'candidates'/(main_name+'_refined')/'groups.json'
    changes=None
    if repaired.exists():
        old=labels_for(data,json.loads((run/'candidates'/main_name/'groups.json').read_text()))
        new=labels_for(data,json.loads(repaired.read_text()))
        cells=[c for a in data['active_atoms'] if old[a]!=new[a] for c in data['atoms'][a]]
        changes=dict(candidate=main_name+'_refined',unique_moved_cells=len(cells),
                     moved_top_cells=sum(data['cells'][c]['original_hierarchy']=='TOP' for c in cells))
    exits={p.name:p.read_text().strip() for p in run.glob('*.exit')}
    assert all(v=='0' for v in exits.values()),exits
    validation=dict(status='PASS',input_hashes_unchanged=True,configuration_unchanged=True,
                     deliveries=checks,logical_repair=changes,stage_exit_codes=exits)
    (run/'validation.json').write_text(json.dumps(validation,indent=2)+'\n')
    source_hashes={p.name:digest(p) for p in sorted((run/'source').iterdir()) if p.is_file()}
    (run/'source_manifest.json').write_text(json.dumps(dict(files=source_hashes,
        publication='Local/server source snapshot only; no new Git commit/push'),indent=2)+'\n')
    selected=[]
    for p in sorted(run.rglob('*')):
        if not p.is_file() or p.is_symlink():continue
        relative=p.relative_to(run)
        # The caller may still be writing this log while the archive is built.
        # validation.json is the immutable validation record in the package.
        if relative == Path('validation.log'):continue
        if relative.parts[0] in ('selected','alternatives','figures','source'):
            selected.append(p)
        elif relative.parts[0]=='candidates' and p.name in ('summary.json','balanced_regions.json','screening.json'):
            selected.append(p)
        elif len(relative.parts)==1 and p.suffix in ('.json','.tsv','.md','.log','.exit','.sh'):
            selected.append(p)
    evidence={str(p.relative_to(run)):digest(p) for p in selected if p.name!='evidence_manifest.json'}
    manifest=run/'evidence_manifest.json';manifest.write_text(json.dumps(dict(files=evidence),indent=2)+'\n')
    if manifest not in selected:selected.append(manifest)
    with tarfile.open(run/'compact_results.tar.gz','w:gz') as archive:
        for p in selected:archive.add(p,arcname=str(p.relative_to(run)),recursive=False)
    print(json.dumps(dict(status='PASS',files=len(evidence),deliveries=checks,logical_repair=changes)),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('run',type=Path);a=p.parse_args();main(a.run)
