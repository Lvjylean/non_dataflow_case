"""Check generated interface contracts before spending time on platform linking."""
import json,sys
from pathlib import Path

run=Path(sys.argv[1]).resolve()
bd_paths=list(run.glob('project/*.srcs/sources_1/bd/*/*.bd'))
assert len(bd_paths)==1,bd_paths
design=json.loads(bd_paths[0].read_text())['design']
memory=design['interface_ports']['M_AXI_GMEM']
parameters=memory['parameters']
assert memory['mode']=='Master'
assert parameters['ADDR_WIDTH']['value']=='64'
assert parameters['FREQ_HZ']['value']=='100000000'
assert parameters['DATA_WIDTH']['value']==('128' if run.name.startswith('vta') else '256')
addressing=design['addressing']
masters=[]
for owner,scope in addressing.items():
    for name,space in scope.get('address_spaces',{}).items():
        if not name.startswith('Data_m_axi_'):continue
        segments=list(space.get('segments',{}).values())
        assert len(segments)==1,(owner,name,segments)
        seg=segments[0]
        assert int(seg['offset'],0)==0,(owner,name,seg)
        assert seg['range']=='1T',(owner,name,seg)
        masters.append({'owner':owner,'name':name,'offset':seg['offset'],'range':seg['range']})
assert len(masters)==5,masters
control=addressing['/']['address_spaces']['S_AXI_CONTROL']
assert control['width']=='16'
pages=sorted(int(s['offset'],0) for s in control['segments'].values())
expected=8 if run.name.startswith('vta') else 2
assert pages==list(range(0,expected*4096,4096)),pages
assert all(s['range']=='4K' for s in control['segments'].values())
xcis=list(run.glob('project/*.srcs/sources_1/bd/*/ip/*reset_sync*/*.xci'))
assert len(xcis)==1,xcis
xci=json.loads(xcis[0].read_text())
def find_values(obj,key):
    out=[]
    if isinstance(obj,dict):
        for k,v in obj.items():
            if k==key and isinstance(v,list):out.extend(str(x.get('value')) for x in v)
            else:out.extend(find_values(v,key))
    elif isinstance(obj,list):
        for v in obj:out.extend(find_values(v,key))
    return out
ext=find_values(xci,'C_EXT_RESET_HIGH'); aux=find_values(xci,'C_AUX_RESET_HIGH')
assert ext and set(ext)=={'0'},ext
assert aux and set(aux)=={'1'},aux
result={'status':'PASS','axi_address_width':64,'axi_data_width':int(parameters['DATA_WIDTH']['value']),'interface_clock_hz':100000000,'masters':masters,'control_page_offsets':pages,'external_reset_active_high':ext,'auxiliary_reset_active_high':aux,'scope':'Generated DDR decoding/control/reset contract; not functional or physical closure.'}
(run/'interface_audit.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
