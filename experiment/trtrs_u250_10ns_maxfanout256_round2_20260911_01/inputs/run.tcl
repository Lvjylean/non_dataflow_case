set run_dir $::env(RUN_DIR)
cd $run_dir
set_param general.maxThreads 4
proc phase {name} {
    set f [open phase.txt w]; puts $f "$name [clock format [clock seconds]]"; close $f
    puts "ROUND2_PHASE=$name"
}
phase OPEN_SYNTH_CHECKPOINT
open_checkpoint input_post_synth.dcp
if {[get_property PART [current_design]] ne "xcu250-figd2104-2L-e"} {error "Part mismatch"}
if {abs([get_property PERIOD [get_clocks ap_clk]]-10.0)>0.00001} {error "Clock period mismatch"}
if {[llength [get_cells -hier -filter {IS_BLACKBOX == 1}]]} {error "Unresolved black boxes"}
source inputs/fanout.tcl
phase CONSTRAIN_POST_SYNTH
fanout_scan post_synth 0 1
write_checkpoint -force constrained_post_synth.dcp
phase OPT
opt_design
# Re-discover nets after optimization to include new drivers and merged connections.
fanout_scan post_opt 0 1
phase PLACE
place_design
write_checkpoint -force post_place.dcp
report_timing_summary -delay_type min_max -file post_place_timing.rpt
report_utilization -file post_place_utilization.rpt
set remaining [fanout_scan post_place 1 0]
set pf [open phys_opt_decision.txt w]
puts $pf "MAX_FANOUT/FORCE_MAX_FANOUT are evaluated during placement. Additional targeted physical optimization is conditional on remaining FD/LUT nets above 256 logical sink pins."
if {[llength $remaining]} {
    puts $pf "RUN: [llength $remaining] eligible nets exceed 256 logical loads after placement."
    for {set round 1} {$round <= 2 && [llength $remaining]} {incr round} {
        phase PHYS_OPT_FANOUT_$round
        set before [llength $remaining]
        phys_opt_design -force_replication_on_nets $remaining
        write_checkpoint -force post_fanout${round}.dcp
        set remaining [fanout_scan post_fanout${round} 1 0]
        puts $pf "Round $round eligible net count: $before -> [llength $remaining]"
        flush $pf
        if {[llength $remaining] >= $before} {puts $pf "Stop repeated replication: no decrease in eligible violation count."; break}
    }
} else {puts $pf "SKIP: placement satisfied the 256 logical-load cap for eligible FD/LUT drivers."}
close $pf
# Route also when a cap is unmet, to measure both outcomes separately without claiming fanout success.
phase ROUTE
route_design
write_checkpoint -force routed.dcp
source inputs/reports.tcl
fanout_scan post_route 1 0
set f [open implementation_complete.txt w]; puts $f [clock format [clock seconds]]; close $f
phase IMPLEMENTATION_COMPLETE
