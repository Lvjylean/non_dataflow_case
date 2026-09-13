import sys,json, pathlib
root=pathlib.Path(sys.argv[1]).resolve()
sys.path.insert(0,str(root/'upstream/tvm-vta/config'))
from vta_config import pkg_config, gen_tcl_vivado
cfg_path=pathlib.Path(sys.argv[2]).resolve() if len(sys.argv)>2 else root/'upstream/tvm-vta/config/vta_config.json'
cfg=json.loads(cfg_path.read_text())
cfg['TARGET']='ultra96'
pkg=pkg_config(cfg)
pkg.fpga_device='xcu250-figd2104-2L-e'
pkg.fpga_per=10
pkg.fpga_freq=100
pkg.include_path=['-I'+str(root/'upstream/tvm-vta/include')]
gen_tcl_vivado(pkg,'config.tcl')
pathlib.Path('config.json').write_text(json.dumps(cfg,indent=2)+'\n')
