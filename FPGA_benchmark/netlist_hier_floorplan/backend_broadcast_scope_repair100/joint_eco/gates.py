"""Timing acceptance is independent of successful structural execution."""
import csv,json,re,sys
from pathlib import Path

def sta(path):
    lines=Path(path).read_text().splitlines();i=next(i for i,x in enumerate(lines) if x.strip().startswith('WNS(ns)'));v=lines[i+2].split()
    return dict(wns=float(v[0]),tns=float(v[1]),setup_failing=int(v[2]),whs=float(v[4]),ths=float(v[5]),hold_failing=int(v[6]))
def slacks(path):
    with Path(path).open() as f:return {(r['endpoint'],r['type']):float(r['slack']) for r in csv.DictReader(f,delimiter='\t')}
def evaluate(before,after,base_sta,new_sta,protected):
    regressions=[];missing=[]
    for key,value in before.items():
        ep,kind=key
        if key not in after:missing.append(key);continue
        # The original positive-sign reference remains binding even when the
        # current incumbent contains a regression at that endpoint.
        floor=0.0 if value>=0 or (kind=='max' and ep in protected) else value
        if after[key]<floor-1e-9:regressions.append(dict(endpoint=ep,type=kind,before=value,after=after[key],floor=floor))
    gates=dict(guard_coverage=not missing,no_new_or_worsened_guard_violation=not regressions,
               global_wns_nonworse=new_sta['wns']>=base_sta['wns'],global_tns_nonworse=new_sta['tns']>=base_sta['tns'],
               hold_nonnegative=new_sta['whs']>=0)
    return dict(accepted=all(gates.values()),gates=gates,before=base_sta,after=new_sta,missing=missing,regressions=regressions)
def main():
    before,after,protected,output=map(Path,sys.argv[1:5])
    result=evaluate(slacks(before/'guard_slacks.tsv'),slacks(after/'guard_slacks.tsv'),sta(before/'timing_summary.rpt'),sta(after/'timing_summary.rpt'),set(json.loads(protected.read_text())))
    output.write_text(json.dumps(result,indent=2)+'\n');print('ACCEPT' if result['accepted'] else 'REJECT')
if __name__=='__main__':main()
