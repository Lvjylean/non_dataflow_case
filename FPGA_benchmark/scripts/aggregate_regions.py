from pathlib import Path
from collections import Counter
refs=Path('primitive_refs.raw').read_text().splitlines()
locs=Path('primitive_locs.raw').read_text().splitlines()
assert len(refs)==len(locs), (len(refs),len(locs))
regions={}
for line in Path('sites_by_region.raw').read_text().splitlines():
 region,sites=line.split('\t',1)
 for site in sites.split(): regions[site]=region
counts=Counter(); unknown=Counter()
for ref,loc in zip(refs,locs):
 if ref in ('GND','VCC'):continue
 if loc not in regions:unknown[ref]+=1;continue
 counts[(regions[loc],ref)]+=1
with Path('clock_region_primitives.tsv').open('w') as f:
 f.write('clock_region\tprimitive_type\tcount\n')
 for (region,ref),count in sorted(counts.items()):f.write(f'{region}\t{ref}\t{count}\n')
Path('audit_summary.txt').write_text(f'Primitive instances: {len(refs)}; mapped nonconstant: {sum(counts.values())}; unmapped nonconstant: {sum(unknown.values())}\nUnmapped types: {dict(unknown)}\nCounts are primitive instances, not occupied CLB sites or LUT resource equivalents.\n')
