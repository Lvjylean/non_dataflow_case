set_param general.maxThreads 4
set root $::env(BENCH_ROOT)
file copy $::env(STUB_RUN)/core_stub.v core_stub.v
exec python3 $root/scripts/buffer_wrapper.py
set f [open top_name.txt r]; set top [string trim [read $f]]; close $f
if {$::env(CORE_KIND) eq "vta"} {
 source $root/scripts/vta_build_bd.tcl
} else {
 create_project -in_memory -part xcu250-figd2104-2L-e
 set rtl $root/upstream/CNNA/reference_ip/hdl/verilog
 read_vhdl [glob $rtl/*.vhd]
 read_verilog [glob $rtl/*.v]
}
read_verilog buffered_wrapper.v
set f [open top_name.txt r]; set top [string trim [read $f]]; close $f
set_property top $top [current_fileset]
synth_design -top $top -part xcu250-figd2104-2L-e -mode out_of_context
if {[llength [get_cells -quiet -hier -filter {IS_BLACKBOX == 1}]]} {error "Unresolved black boxes"}
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
