cd $::env(RUN_DIR)
set_param general.maxThreads 4
open_checkpoint routed.dcp
source inputs/fanout_audit_v2.tcl
file mkdir audit_final
cd audit_final
fanout_scan post_route_audit 1 0
set f [open clocks.rpt w]
foreach c [get_clocks] {puts $f "$c [get_property PERIOD $c]"}
close $f
set f [open verified.txt w]; puts $f [clock format [clock seconds]]; close $f
