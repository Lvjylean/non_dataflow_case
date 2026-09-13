set run_dir $::env(RUN_DIR)
cd $run_dir
set_param general.maxThreads 4
proc phase {name} {
    set f [open phase.txt w]; puts $f "$name [clock format [clock seconds]]"; close $f
    puts "ORB_PHASE=$name"
}
phase OPEN_ORIGINAL_SYNTH
open_checkpoint $::env(BASELINE_DIR)/post_synth.dcp
if {[get_property PART [current_design]] ne "xcu250-figd2104-2L-e"} {error "Part mismatch"}
if {abs([get_property PERIOD [get_clocks ap_clk]]-5.0)>0.00001} {error "Clock mismatch"}
if {[llength [get_cells -hier -filter {IS_BLACKBOX == 1}]]} {error "Unresolved black boxes"}
source inputs/fanout.tcl
phase OPT
opt_design
phase RESET_IDENTITY_BUFFERS
source inputs/reset_buffer.tcl
write_checkpoint -force buffered_post_opt.dcp
phase FORCE_MAX_FANOUT_256
fanout_scan post_opt 0 1
write_checkpoint -force constrained_post_opt.dcp
phase PLACE
place_design
write_checkpoint -force post_place.dcp
report_utilization -file post_place_utilization.rpt
report_timing_summary -file post_place_timing.rpt
set remaining [fanout_scan post_place 1 0]
for {set round 1} {$round <= 3 && [llength $remaining]} {incr round} {
    phase PHYS_OPT_FANOUT_$round
    set before [llength $remaining]
    phys_opt_design -force_replication_on_nets $remaining
    write_checkpoint -force post_fanout${round}.dcp
    set remaining [fanout_scan post_fanout${round} 1 0]
    if {[llength $remaining] >= $before} {break}
}
phase ROUTE
route_design
write_checkpoint -force routed.dcp
phase REPORTS
source inputs/reports.tcl
fanout_scan post_route 1 0
report_high_fanout_nets -max_nets 50 -file high_fanout.rpt
set f [open implementation_complete.txt w]; puts $f [clock format [clock seconds]]; close $f
phase IMPLEMENTATION_COMPLETE
