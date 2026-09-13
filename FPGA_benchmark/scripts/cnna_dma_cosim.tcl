open_project cnna_dma_hls
set_top cnna_dma
set f [open $::env(BENCH_ROOT)/hls/cnna_dma.cpp r]; set code [read $f]; close $f
set code [string map {offset=slave {depth=3 offset=slave}} $code]
set f [open simulation_dma.cpp w]; puts $f $code; close $f
add_files simulation_dma.cpp
add_files -tb $::env(BENCH_ROOT)/hls/cnna_dma_test.cpp
open_solution soln -flow_target vivado
set_part xcu250-figd2104-2L-e
create_clock -period 10
csim_design
csynth_design
cosim_design -rtl verilog
exit
