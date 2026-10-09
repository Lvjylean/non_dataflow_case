#!/usr/bin/env python3
"""Select hot U250 SLL bundles from Vivado's initial SLL Assignment table."""
import argparse
import hashlib
import json
from pathlib import Path
import re


def parse(text):
    marker = 'Estimated SLL Demand Per Column:'
    tables = []
    for match in re.finditer(r'Number SLLs per Column:\s*(\d+)\s*' + re.escape(marker), text):
        capacity = int(match[1])
        rows = []
        tail = text[match.end():]
        for line in tail.splitlines()[1:4]:
            row = re.fullmatch(r'\s*SLR \[(\d+)-(\d+)\](.*?)\s+Demand:\s*(\d+)\s+Available:\s*(\d+)\s+Utilization\(%\):\s*([\d.]+)\s*', line)
            if not row:
                raise ValueError('Incomplete SLL demand table')
            lower, upper = int(row[1]), int(row[2])
            pairs = re.findall(r'(\d+)\s*\(\s*(\d+)%\)', row[3])
            if capacity != 1440 or len(pairs) != 16 or upper != lower + 1 or int(row[5]) != 23040:
                raise ValueError('Unexpected device geometry in SLL demand table')
            if sum(int(demand) for demand, _ in pairs) != int(row[4]):
                raise ValueError('SLL column demand does not add up')
            for column, (demand, rounded) in enumerate(pairs):
                rows.append(dict(lower=f'SLR{lower}', upper=f'SLR{upper}', column=column,
                                 demand=int(demand), capacity=capacity,
                                 utilization=int(demand)/capacity,
                                 reported_percent=int(rounded)))
        if {(r['lower'], r['upper']) for r in rows} != {('SLR0','SLR1'),('SLR1','SLR2'),('SLR2','SLR3')}:
            raise ValueError('Missing or duplicate SLR boundary')
        tables.append(rows)
    if len(tables) != 1:
        raise ValueError(f'Expected one full-route initial SLL table, found {len(tables)}')
    return tables[0]


def make_plan(log, output, clock='ap_clk'):
    raw = Path(log).read_bytes()
    rows = parse(raw.decode(errors='replace'))
    chosen = [r for r in rows if r['demand'] * 5 >= r['capacity'] * 4]
    result = dict(schema='u250-sll-reservation-v1', threshold=0.8, blocked_fraction=1/3,
                  source_log=str(Path(log).resolve()), source_log_sha256=hashlib.sha256(raw).hexdigest(),
                  metric='initial SLL Assignment estimated demand based on final placement',
                  column_order='left-to-right native Laguna tile X', clock_port=clock,
                  rows=rows, hotspots=chosen, reserved_per_hot_bundle=480,
                  reserved_total=480*len(chosen))
    output = Path(output); output.mkdir(parents=True, exist_ok=False)
    (output/'plan.json').write_text(json.dumps(result, indent=2)+'\n')
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', clock):
        raise ValueError('Clock port must be a plain identifier')
    bundles = ' '.join('{%s %s %d}' % (r['lower'],r['upper'],r['column']) for r in chosen)
    (output/'plan.tcl').write_text('set sll_plan {schema u250-sll-reservation-v1 clock_port %s bundles {%s}}\n' % (clock,bundles))
    return result


if __name__ == '__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('log',type=Path); ap.add_argument('output',type=Path)
    args=ap.parse_args()
    print(json.dumps(make_plan(args.log,args.output),indent=2))
