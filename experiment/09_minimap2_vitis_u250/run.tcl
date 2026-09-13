open_project hls
set_top device_chain_kernel
add_files {/Projects/jinyang/workspace/non_dataflow_crossSLR/case/minimap2-acceleration/kernel/hls/src/device_kernel.cpp} -cflags {-std=c++11}
open_solution sol -flow_target vitis
set_part {xcu250-figd2104-2L-e}
create_clock -period 5 -name default
csynth_design
exit
