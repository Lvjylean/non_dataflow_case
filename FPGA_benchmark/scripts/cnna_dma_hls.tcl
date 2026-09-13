open_project cnna_dma_hls
set_top cnna_dma
add_files $::env(BENCH_ROOT)/hls/cnna_dma.cpp
add_files -tb $::env(BENCH_ROOT)/hls/cnna_dma_test.cpp
open_solution soln -flow_target vivado
set_part xcu250-figd2104-2L-e
create_clock -period 10
csim_design
csynth_design
export_design -format ip_catalog
exit
