if {![info exists ::env(HLS_OUTPUT_DIR)]} {error "Set HLS_OUTPUT_DIR"}
set output $::env(HLS_OUTPUT_DIR)
if {[file pathtype $output] ne "absolute" || [file exists $output]} {error "Output must be new and absolute"}
open_project $output
set_top tvl1_accel
add_files {/Projects/jinyang/workspace/non_dataflow_crossSLR/case/experiment/vision_tvl1_optical_flow_1024x1024_npc2__LUT_59p6pctSLR__20260911_v04/sources/xf_tvl1_accel.cpp} -cflags {-std=c++14 -I/Projects/jinyang/workspace/non_dataflow_crossSLR/case/experiment/vision_tvl1_optical_flow_1024x1024_npc2__LUT_59p6pctSLR__20260911_v04/sources -I/Projects/jinyang/workspace/non_dataflow_crossSLR/case/experiment/vision_tvl1_optical_flow_1024x1024_npc2__LUT_59p6pctSLR__20260911_v04/library}
open_solution sol -flow_target vivado
set_part {xcu250-figd2104-2L-e}
create_clock -period 5
csynth_design
exit
