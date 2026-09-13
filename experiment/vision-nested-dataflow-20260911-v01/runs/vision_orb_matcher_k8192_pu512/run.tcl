open_project hls
set_top bfmatcher_accel
add_files {/Projects/jinyang/workspace/non_dataflow_crossSLR/case/experiment/vision-nested-dataflow-20260911-v01/cases/vision_orb_matcher_k8192_pu512/xf_bfmatcher_accel.cpp} -cflags {-std=c++14 -I/Projects/jinyang/workspace/non_dataflow_crossSLR/case/experiment/vision-nested-dataflow-20260911-v01/cases/vision_orb_matcher_k8192_pu512 -I/Projects/jinyang/workspace/non_dataflow_crossSLR/case/experiment/vision-nested-dataflow-20260911-v01/vision/L1/include}
open_solution sol -flow_target vivado
set_part {xcu250-figd2104-2L-e}
create_clock -period 5
csynth_design
exit
