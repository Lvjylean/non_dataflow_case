"""Verify complete native candidate equivalence and recorded acquisition cost."""
import argparse
import csv
import hashlib
import json
from pathlib import Path

TABLES = ('ji_candidates.tsv','ji_cones.tsv','ji_cells.tsv','ji_edges.tsv',
          'ji_nets.tsv','ji_slacks.tsv','ji_capacity.tsv',
          'locality/template_status.tsv','locality/through_slacks.tsv')


def table(path):
    with path.open(newline='') as stream:
        rows = list(csv.reader(stream, delimiter='\t'))
    if not rows or any(len(row) != len(rows[0]) for row in rows):
        raise ValueError('Malformed table:'+str(path))
    return rows[0], sorted(rows[1:])


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(code, out):
    modes = ('reference','enabled','stale')
    for mode in modes:
        if not (out/mode/'NATIVE_COMPLETE').is_file():
            raise ValueError('Incomplete native mode:'+mode)
    evidence = []
    for relative in (*TABLES,'joint_candidates.json','locality/final_plan.tcl','native_plan.tcl'):
        paths = [out/mode/relative for mode in modes]
        values = [table(p) if p.suffix == '.tsv' else json.loads(p.read_text())
                  if p.suffix == '.json' else p.read_bytes() for p in paths]
        if values[0] != values[1] or values[0] != values[2]:
            raise ValueError('Complete candidate/native plan mismatch:'+relative)
        evidence.append(dict(path=relative,sha256={m:sha(p) for m,p in zip(modes,paths)}))
    counters = {mode:dict(table(out/mode/'locality/candidate_input_reuse.tsv')[1]) for mode in modes}
    if int(counters['enabled']['input_cell_hits']) <= 0 or int(counters['enabled']['load_hits']) <= 0:
        raise ValueError('Fixture did not exercise native input/load reuse')
    if int(counters['stale']['input_cell_hits']) or int(counters['stale']['load_hits']):
        raise ValueError('Stale native connection snapshot produced a hit')
    calls = {mode:dict(table(out/mode/'native_calls.tsv')[1]) for mode in modes}
    result = dict(schema='native-candidate-input-equivalence-v2',status='PASS',
                  complete_tables_equal=True,actual_native_plans_equal=True,
                  stale_snapshot_native_fallback=True,native_calls=calls,
                  connection_counters=counters,evidence=evidence,
                  source_hashes={str(p.relative_to(code)):sha(p) for p in sorted(code.rglob('*'))
                                 if p.is_file() and p.suffix in {'.py','.tcl','.v','.sv'}},
                  scope='small native fixture only; timings do not predict full-case speed')
    (out/'candidate_readback_evidence.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


if __name__ == '__main__':
    parser=argparse.ArgumentParser();parser.add_argument('code',type=Path);parser.add_argument('out',type=Path)
    args=parser.parse_args();print(json.dumps(verify(args.code,args.out)))
