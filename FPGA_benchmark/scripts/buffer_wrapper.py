"""Wrap an unchanged synthesized core with a real global clock buffer."""
import re
from pathlib import Path
s=Path('core_stub.v').read_text()
s=re.sub(r'/\*.*?\*/', '', s, flags=re.S)
s=re.sub(r'//[^\n]*', '', s)
m=re.search(r'module\s+(\w+)\s*\(',s)
if not m: raise ValueError('No stub module')
core=m[1]
ports=[]
for direction, width, name in re.findall(r'\b(input|output|inout)\s+(\[[^]]+\]\s*)?(\w+)\s*;',s):
    ports.append((direction,width.strip(),name))
if not ports or 'aclk' not in [p[2] for p in ports]: raise ValueError('Missing clock or ports')
assert len({p[2] for p in ports})==len(ports)
top=core+'_u250_buffered'
lines=['module '+top+'(', ',\n'.join('  '+d+' wire '+(w+' ' if w else '')+n for d,w,n in ports),');','wire core_clock;','BUFG clock_buffer (.I(aclk), .O(core_clock));',core+' core (',',\n'.join('  .'+n+'('+('core_clock' if n=='aclk' else n)+')' for _,_,n in ports),');','endmodule','']
Path('buffered_wrapper.v').write_text('\n'.join(lines))
Path('top_name.txt').write_text(top+'\n')
