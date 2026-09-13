"""Create a test-only overlay; never modify pinned accelerator sources."""
import hashlib,json,sys
from pathlib import Path
root=Path(sys.argv[1])
src=root/'upstream/tvm-vta/tests/hardware/common/test_lib.cc'
s=src.read_text()
old='acc_T src_val = inputs[i][j + vector_size];'
new='acc_T src_val = use_imm ? acc_T(0) : inputs[i][j + vector_size];'
assert s.count(old)==1
Path('test_lib_overlay.cc').write_text(s.replace(old,new))
main=root/'upstream/tvm-vta/hardware/xilinx/sim/vta_test.cc'
test=main.read_text()
assert test.count('blocked_gemm_test(256, 256,')==2
Path('vta_test_overlay.cc').write_text(test.replace('blocked_gemm_test(256, 256,','blocked_gemm_test(VTA_BLOCK_OUT*8, VTA_BLOCK_OUT*8,'))
Path('test_overlay.json').write_text(json.dumps({'source':str(src),'source_sha256':hashlib.sha256(src.read_bytes()).hexdigest(),'old':old,'new':new,'scope':'Test oracle only: do not read the absent second input in immediate mode.'},indent=2)+'\n')
