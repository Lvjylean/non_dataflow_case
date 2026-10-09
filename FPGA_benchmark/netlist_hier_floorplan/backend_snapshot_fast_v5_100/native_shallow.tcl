# Native regional mutation and mobility test on a real placed, high-fanout fixture.
if {[catch {
lassign $argv code input out
file mkdir $out
source $code/code/regional/core.tcl
source $code/code/regional/regional.tcl
source $code/code/regional/execution.tcl
execopt::configure fast
set_param general.maxThreads 8
open_checkpoint $input
sb::spatial_cache
set plan [rf::discover $out {} {root/Q}]
rf::require [expr {[llength [dict get $plan roots]] == 1}] "Native over-limit root missing"
set root [lindex [dict get $plan roots] 0]
rf::require [expr {[llength [dict get $root sinks]] == 512}] "Fixture sink count changed"
rf::require [expr {[dict size [dict get $plan fixed]] == 0}] "Regional endpoints unexpectedly frozen"
foreach n [dict get $root nodes] {rf::require [expr {[dict get $n kind] ne "source"}] "Redundant source tier"}
set plan [rf::apply $plan $out]
rf::verify $plan $out/after_edit 0
place_design -no_psip -no_bufg_opt
rf::verify $plan $out/post_place 1
route_design
rf::verify $plan $out/post_route 1
report_route_status -file $out/route_status.rpt
report_timing_summary -file $out/timing_summary.rpt
write_checkpoint $out/post_route.dcp
set f [open $out/plan.tcl w];puts $f [list set native_plan $plan];close $f
set f [open $out/PASS w];puts $f "PASS native full leaf equality, shallow tree, destination regions, movable LUTs, placement and routing";close $f
close_design
exit
} message options]} {puts stderr [dict get $options -errorinfo];exit 1}
