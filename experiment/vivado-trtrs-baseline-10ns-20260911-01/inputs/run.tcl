set run_dir $::env(RUN_DIR)
cd $run_dir
set_param general.maxThreads 4
create_project baseline ./project -part xcu250-figd2104-2L-e -force
foreach f [lsort [glob ./rtl/*_ip.tcl]] {source $f}
read_verilog [lsort [glob ./rtl/*.v]]
read_xdc ./inputs/clock.xdc
synth_design -top kernel_trtrs_0 -part xcu250-figd2104-2L-e -mode out_of_context -flatten_hierarchy none -no_iobuf
if {[llength [get_cells -hier -filter {IS_BLACKBOX == 1}]]} {error "Unresolved black boxes"}
report_utilization -hierarchical -file post_synth_utilization.rpt
report_timing_summary -delay_type min_max -file post_synth_timing.rpt
write_checkpoint -force post_synth.dcp
# Standard default implementation only; no physical optimization or floorplanning.
opt_design
place_design
report_utilization -file post_place_utilization.rpt
report_timing_summary -delay_type min_max -file post_place_timing.rpt
write_checkpoint -force post_place.dcp
route_design
write_checkpoint -force routed.dcp
source ./inputs/reports.tcl
set f [open implementation_complete.txt w]; puts $f [clock format [clock seconds]]; close $f
