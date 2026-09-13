set root $::env(BENCH_ROOT)/upstream/CNNA/src/src
open_project cnna_hls
set_top cnn
add_files $root/hwcore/cnn/cnn.cpp -cflags "-D__SYNTHESIS__ -I$root -DP_data_P=2 -DP_data_W=16 -DP_input_width=128 -DP_output_width=128 -DP_pe_n=8 -DP_pe_bw_n=8 -DP_wbuf_size=1547 -DP_data_buf_clb_size=4096 -DP_data_buf_clb_n=3 -DP_data_buf_shift_size=192 -DP_data_out_n=3 -DP_pool_size=1024"
open_solution soln -flow_target vivado
set_part xcu250-figd2104-2L-e
create_clock -period 10
csynth_design
exit
