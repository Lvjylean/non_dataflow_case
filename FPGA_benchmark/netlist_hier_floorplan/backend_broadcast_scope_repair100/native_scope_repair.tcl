# Native injected scope violation, local physical repair, routing and reopen.
if {[catch {
lassign $argv code out mode fixture
file mkdir $out
source $code/checkpoint_io.tcl
source $code/physical_eco.tcl
source $code/code/regional/core.tcl
source $code/code/regional/regional.tcl
source $code/code/regional/local_broadcast.tcl
lb::install
source $code/code/regional/scope_repair.tcl
set_param general.maxThreads 8
if {$mode eq "reopen"} {
    open_checkpoint $out/post_route.dcp
    source $out/plan.tcl
    sb::verify $sb_plan $out/reopened 1
    plg::assert_routed $out/reopened/physical
    report_timing_summary -delay_type min_max -file $out/reopened/timing_summary.rpt
    set f [open $out/REOPEN_PASS w];puts $f PASS;close $f
    close_design;exit
}
open_checkpoint $fixture/post_route.dcp
source $fixture/plan.tcl
set plan $sb_plan
set name ""
dict for {n item} [dict get $plan local_broadcast graph replicas] {
    if {[sb::ref $n] in {FDRE FDSE}} {set name $n;set target [dict get $item slr];break}
}
sb::require [expr {$name ne ""}] "Native fixture has no FF replica"
set obj [sb::cell $name];set original [get_property LOC $obj]
set wrong [expr {$target eq "SLR0" ? "SLR1" : "SLR0"}]
set outside ""
foreach site [get_sites -of_objects [get_slrs $wrong] -filter {SITE_TYPE == SLICEL}] {
    if {![llength [get_cells -quiet -of_objects $site]]} {set outside $site;break}
}
sb::require [expr {$outside ne ""}] "No empty wrong-SLR site for native injection"
plg::clean_sites [list $original $outside] $out/injection_cleanup
remove_cells_from_pblock [get_pblocks localrep_$target] $obj
unplace_cell $obj
place_cell [list $name $outside]
set_property IS_LOC_FIXED false $obj
set_property IS_BEL_FIXED false $obj
lb::bind $name $target
sb::verify $plan $out/injected_structure 0
set injected [scr::scan $plan $out/injected]
sb::require [expr {[dict size $injected] == 1}] "Native injection did not create exactly one scope outlier"
set geometry {}
foreach c [get_cells -hier -filter {IS_PRIMITIVE == 1}] {
    if {[get_property NAME $c] ne $name} {dict set geometry [get_property NAME $c] [list [get_property LOC $c] [get_property BEL $c]]}
}
set plan [scr::repair $plan $out/repair]
dict for {n pos} $geometry {
    sb::require [expr {[list [get_property LOC [sb::cell $n]] [get_property BEL [sb::cell $n]]] eq $pos}] "Native repair changed an unrelated cell's placement: $n"
}
# The second pass must be a true no-op and must not disturb repaired geometry.
set before [list [get_property LOC $obj] [get_property BEL $obj]]
set plan [scr::repair $plan $out/noop]
sb::require [expr {$before eq [list [get_property LOC $obj] [get_property BEL $obj]]}] "No-op scope repair changed placement"
sb::save $plan $out/plan.tcl
sb::verify $plan $out/repaired_structure 1
update_clock_routing
plg::before_route $out/physical_before_route
route_design
sb::verify $plan $out/routed_structure 1
plg::assert_routed $out/physical_routed
write_checkpoint -force $out/post_route.dcp
report_timing_summary -delay_type min_max -file $out/timing_summary.rpt
set f [open $out/NATIVE_PASS w];puts $f PASS;close $f
puts NATIVE_SCOPE_REPAIR_PASS
close_design;exit
} message options]} {
puts stderr $message
puts stderr [dict get $options -errorinfo]
exit 1
}
