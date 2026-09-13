open_project hls
set_top ISPPipeline_accel
add_files {/Projects/jinyang/workspace/non_dataflow_crossSLR/case/experiment/vision-nested-dataflow-20260911-v04/cases/vision_isp_hdr_8k_npc4/xf_isp_accel.cpp} -cflags {-std=c++14 -I/Projects/jinyang/workspace/non_dataflow_crossSLR/case/experiment/vision-nested-dataflow-20260911-v04/cases/vision_isp_hdr_8k_npc4 -I/Projects/jinyang/workspace/non_dataflow_crossSLR/case/experiment/vision-nested-dataflow-20260911-v04/vision/L1/include}
open_solution sol -flow_target vivado
set_part {xcu250-figd2104-2L-e}
create_clock -period 5
csynth_design
exit
