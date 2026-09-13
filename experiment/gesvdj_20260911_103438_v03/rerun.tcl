if {![info exists ::env(HLS_OUTPUT_DIR)]} {error "Set HLS_OUTPUT_DIR to a new absolute directory"}
set output $::env(HLS_OUTPUT_DIR)
if {[file pathtype $output] ne "absolute" || [file exists $output]} {error "Output must be new and absolute"}
open_project $output
set_top kernel_gesvdj_0
add_files {/Projects/jinyang/workspace/non_dataflow_crossSLR/case/experiment/gesvdj_20260911_103438_v03/sources/kernel.cpp} -cflags {-std=c++14 -I/Projects/jinyang/workspace/non_dataflow_crossSLR/case/experiment/gesvdj_20260911_103438_v03/library/solver/L2/include -I/Projects/jinyang/workspace/non_dataflow_crossSLR/case/experiment/gesvdj_20260911_103438_v03/library/solver/L1/include -I/Projects/jinyang/workspace/non_dataflow_crossSLR/case/experiment/gesvdj_20260911_103438_v03/library/security/L1/include}
open_solution sol -flow_target vivado
set_part {xcu250-figd2104-2L-e}
create_clock -period 5.0 -name default
csynth_design
exit
