open_project sim
set_top kernel_geqrf_0
add_files {/Projects/jinyang/workspace/non_dataflow_crossSLR/case/experiment/geqrf_20260911_105252_v05/sources/kernel.cpp} -cflags {-std=c++14 -O2 -I/Projects/jinyang/workspace/non_dataflow_crossSLR/case/experiment/geqrf_20260911_105252_v05/library/solver/L2/include -I/Projects/jinyang/workspace/non_dataflow_crossSLR/case/experiment/geqrf_20260911_105252_v05/library/solver/L1/include}
add_files -tb {/Projects/jinyang/workspace/non_dataflow_crossSLR/case/experiment/geqrf_20260911_105252_v05/validation/tb.cpp} -cflags {-std=c++14 -O2 -DTEST_N=768 -DTEST_KIND=4}
open_solution sol -flow_target vivado
set_part {xcu250-figd2104-2L-e}
create_clock -period 5
csim_design
exit
