open_project hls
set_top mean_shift_accel
add_files {/Projects/jinyang/workspace/non_dataflow_crossSLR/case/experiment/vision-nested-dataflow-20260911-v01/cases/vision_meanshift_1080p_objects10/xf_mean_shift_accel.cpp} -cflags {-std=c++14 -I/Projects/jinyang/workspace/non_dataflow_crossSLR/case/experiment/vision-nested-dataflow-20260911-v01/cases/vision_meanshift_1080p_objects10 -I/Projects/jinyang/workspace/non_dataflow_crossSLR/case/experiment/vision-nested-dataflow-20260911-v01/vision/L1/include}
open_solution sol -flow_target vivado
set_part {xcu250-figd2104-2L-e}
create_clock -period 5
csynth_design
exit
