cd $::env(RUN_DIR)
open_project hls
set_top bfmatcher_accel
set flags "-std=c++14 -I$::env(RUN_DIR)/sources -I$::env(RUN_DIR)/library"
add_files sources/xf_bfmatcher_accel.cpp -cflags $flags
add_files -tb inputs/tb.cpp -cflags $flags
open_solution sol -flow_target vivado
set_part xcu250-figd2104-2L-e
create_clock -period 5
csim_design -clean
csynth_design
exit
