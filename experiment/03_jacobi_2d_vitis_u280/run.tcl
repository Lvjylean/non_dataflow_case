open_project hls
set_top kernel
add_files {/Projects/jinyang/workspace/non_dataflow_crossSLR/case/allo-pldi24-artifact/polybench/vitis/jacobi-2d/jacobi-2d.cpp} -cflags {}
open_solution sol -flow_target vivado
set_part {xcu280-fsvh2892-2L-e}
create_clock -period 3.33 -name default
csynth_design
exit
