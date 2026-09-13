open_project hls
set_top tvl1_accel
add_files {/Projects/jinyang/workspace/non_dataflow_crossSLR/case/experiment/vision_tvl1_optical_flow_512x512_npc2__LUT_60p1pctSLR__20260911_v02/sources/xf_tvl1_accel.cpp} -cflags {-std=c++14 -I/Projects/jinyang/workspace/non_dataflow_crossSLR/case/experiment/vision_tvl1_optical_flow_512x512_npc2__LUT_60p1pctSLR__20260911_v02/sources -I/Projects/jinyang/workspace/non_dataflow_crossSLR/case/experiment/vision_tvl1_optical_flow_512x512_npc2__LUT_60p1pctSLR__20260911_v02/library}
open_solution sol -flow_target vivado
set_part {xcu250-figd2104-2L-e}
create_clock -period 5
csynth_design
exit
