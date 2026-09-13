open_project hls
set_top kernel_gtsv_0
add_files {/Projects/jinyang/workspace/non_dataflow_crossSLR/case/experiment/gtsv_20260911_103218_v02/sources/kernel.cpp} -cflags {-std=c++14 -I/Projects/jinyang/workspace/non_dataflow_crossSLR/case/experiment/gtsv_20260911_103218_v02/library/solver/L2/include -I/Projects/jinyang/workspace/non_dataflow_crossSLR/case/experiment/gtsv_20260911_103218_v02/library/solver/L1/include -I/Projects/jinyang/workspace/non_dataflow_crossSLR/case/experiment/gtsv_20260911_103218_v02/library/security/L1/include}
open_solution sol -flow_target vivado
set_part {xcu250-figd2104-2L-e}
create_clock -period 5.0 -name default
csynth_design
exit
