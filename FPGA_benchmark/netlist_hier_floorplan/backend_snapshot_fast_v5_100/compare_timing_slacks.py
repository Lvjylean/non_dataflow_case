"""Compare full endpoint coverage and values; no sampling or tolerance at gates."""
import argparse
import csv
import json
from pathlib import Path


def read(path):
    rows = {}
    for r in csv.DictReader(Path(path).open(), delimiter='\t'):
        if r['pin'] in rows:
            raise ValueError('Duplicate endpoint: '+r['pin'])
        rows[r['pin']] = {k: float(r[k]) if r[k] else None for k in ['max', 'min']}
    return rows


def compare(reference, actual, tolerance=0):
    failures = []
    max_difference = 0
    counts = dict(max=0, min=0)
    for pin in sorted(reference.keys() | actual.keys()):
        if pin not in reference or pin not in actual:
            failures.append(dict(pin=pin, reason='endpoint_set'))
            continue
        for kind in ['max', 'min']:
            a, b = reference[pin][kind], actual[pin][kind]
            if (a is None) != (b is None):
                failures.append(dict(pin=pin, kind=kind, reason='coverage', reference=a, actual=b))
            elif a is not None:
                delta=abs(a-b);max_difference=max(max_difference,delta);counts[kind]+=1
                if not delta <= tolerance:
                    failures.append(dict(pin=pin, kind=kind, reason='slack', reference=a, actual=b))
    return dict(status='PASS' if not failures else 'FAIL', endpoints=len(reference),
                timed=counts, max_difference_ns=max_difference, failures=len(failures),
                examples=failures[:20], tolerance_ns=tolerance)


def main():
    p=argparse.ArgumentParser();p.add_argument('reference');p.add_argument('actual');p.add_argument('output')
    args=p.parse_args();result=compare(read(args.reference),read(args.actual))
    Path(args.output).write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result));return result['status']!='PASS'


if __name__=='__main__':raise SystemExit(main())
