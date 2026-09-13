set root $::env(BENCH_ROOT)/upstream/tvm-vta
source $::env(VTA_HLS_RUN)/config.tcl
open_project simulation
set_top vta
add_files $root/hardware/xilinx/src/vta.cc -cflags $CFLAGS
add_files -tb $root/hardware/xilinx/sim/vta_test.cc -cflags $CFLAGS
add_files -tb $root/tests/hardware/common/test_lib.cc -cflags $CFLAGS
open_solution soln -flow_target vivado
set_part xcu250-figd2104-2L-e
create_clock -period 10
csim_design
exit
