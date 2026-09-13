set_param general.maxThreads 4
set root $::env(BENCH_ROOT)
open_checkpoint $::env(BASE_DCP)
write_verilog -mode synth_stub core_stub.v
close_project
exec python3 $root/scripts/buffer_wrapper.py
set f [open top_name.txt r]; set top [string trim [read $f]]; close $f
create_project -in_memory -part xcu250-figd2104-2L-e
read_verilog core_stub.v
read_verilog buffered_wrapper.v
synth_design -top $top -part xcu250-figd2104-2L-e -mode out_of_context
write_checkpoint wrapper_only.dcp
close_project
open_checkpoint wrapper_only.dcp
read_checkpoint -cell core $::env(BASE_DCP)
if {[llength [get_cells -quiet -hier -filter {IS_BLACKBOX == 1}]]} {error "Unresolved black boxes"}
# The actual wrapper clock buffer now owns the global clock tree.
foreach c [get_clocks -quiet] {delete_clocks $c}
create_clock -name core_clk -period 10 [get_ports aclk]
set_input_delay 1 -clock core_clk [get_ports -filter {DIRECTION == IN && NAME != aclk}]
set_output_delay 1 -clock core_clk [all_outputs]
write_checkpoint post_synth.dcp
report_utilization -hierarchical -file post_synth_utilization.rpt
opt_design
place_design
phys_opt_design
write_checkpoint post_place.dcp
route_design
write_checkpoint routed.dcp
source $root/scripts/reports.tcl
exit
