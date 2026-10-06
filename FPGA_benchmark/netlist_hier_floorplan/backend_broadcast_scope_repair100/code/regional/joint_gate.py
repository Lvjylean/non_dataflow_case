"""Placed setup/hold guard; returns a bounded retry list, never routes a rejection."""
import argparse
import csv
import json
import os
from pathlib import Path


def slacks(path):
    with Path(path).open() as f:
        return {(r['pin'], k):float(r[k]) for r in csv.DictReader(f,delimiter='\t')
                for k in ['max','min'] if r[k]}


def timing(path):
    lines=Path(path).read_text().splitlines()
    i=next(i for i,line in enumerate(lines) if line.strip().startswith('WNS(ns)'))
    v=lines[i+2].split()
    return dict(wns=float(v[0]),tns=float(v[1]),whs=float(v[4]),ths=float(v[5]))


def evaluate(before,after,mapping,old,new,candidates,wns_policy='nonworse'):
    if wns_policy not in {'nonworse','positive'}:
        raise ValueError('Unknown WNS policy: '+wns_policy)
    failures=[]
    for (pin,kind),value in before.items():
        floor=min(0.0,value)
        if (pin,kind) not in after or after[pin,kind]<floor-1e-9:
            failures.append(dict(pin=pin,kind=kind,floor=floor,after=after.get((pin,kind))))
    for row in mapping:
        for kind in ['max','min']:
            key=(row['original'],kind)
            if key not in before:
                continue
            floor=min(0.0,before[key])
            newkey=(row['pin'],kind)
            if newkey not in after or after[newkey]<floor-1e-9:
                failures.append(dict(pin=row['pin'],kind=kind,floor=floor,after=after.get(newkey),owner=row['owner']))
    global_nonworse=(new['wns']>=old['wns']-1e-9 and new['tns']>=old['tns']-1e-9
                 and new['whs']>=min(0.0,old['whs']) and new['ths']>=old['ths'])
    wns_pass = new['wns'] > 0 if wns_policy == 'positive' else new['wns'] >= old['wns']-1e-9
    global_pass=(wns_pass and new['tns']>=old['tns']-1e-9
                 and new['whs']>=min(0.0,old['whs']) and new['ths']>=old['ths'])
    rejected={f['owner'] for f in failures if 'owner' in f}
    # Unknown/global side effects cannot be assigned to a safe smaller subset.
    if any('owner' not in f for f in failures) or (not global_pass and not rejected):
        rejected=set(candidates['keep'])
    # Atomic groups include shared combinational/input resources.
    changed=True
    while changed:
        changed=False
        used=set().union(*(set(candidates['owners'][k]) for k in rejected)) if rejected else set()
        for k in candidates['keep']:
            if k not in rejected and used.intersection(candidates['owners'][k]):
                rejected.add(k);changed=True
    return dict(accepted=not failures and global_pass,failures=failures,global_nonworse=global_nonworse,
                wns_policy=wns_policy,global_policy_pass=global_pass,
                before=old,after=new,reject_ids=sorted(rejected))


def main():
    ap=argparse.ArgumentParser();ap.add_argument('before',type=Path);ap.add_argument('after',type=Path)
    ap.add_argument('--wns-policy',choices=['nonworse','positive'],default=os.environ.get('JI_WNS_POLICY','nonworse'))
    args=ap.parse_args();b=args.before;a=args.after
    candidates=json.loads((b.parent/'joint_candidates.json').read_text())
    with (b/'mapping.tsv').open() as f:mapping=list(csv.DictReader(f,delimiter='\t'))
    result=evaluate(slacks(b/'slacks.tsv'),slacks(a/'slacks.tsv'),mapping,
                    timing(b/'timing_summary.rpt'),timing(a/'timing_summary.rpt'),candidates,args.wns_policy)
    (a/'acceptance.json').write_text(json.dumps(result,indent=2)+'\n')
    (a/'reject_ids.json').write_text(json.dumps(result['reject_ids'],indent=2)+'\n')
    print('ACCEPT' if result['accepted'] else 'REJECT')


if __name__=='__main__':main()
