set root $::env(BENCH_ROOT)/upstream/tvm-vta
source $::env(VTA_HLS_RUN)/config.tcl
exec python3 $::env(BENCH_ROOT)/scripts/vta_test_overlay.py $::env(BENCH_ROOT)
set debug_flags "$CFLAGS -I$root/tests/hardware/common -I$root/hardware/xilinx/sim -fsanitize=address -fno-omit-frame-pointer"
set ::env(ASAN_OPTIONS) detect_leaks=0
open_project simulation
set_top vta
add_files $root/hardware/xilinx/src/vta.cc -cflags $debug_flags
add_files -tb vta_test_overlay.cc -cflags $debug_flags
add_files -tb test_lib_overlay.cc -cflags $debug_flags
open_solution soln -flow_target vivado
set_part xcu250-figd2104-2L-e
create_clock -period 10
csim_design -ldflags "-fsanitize=address -static-libasan"
exit
