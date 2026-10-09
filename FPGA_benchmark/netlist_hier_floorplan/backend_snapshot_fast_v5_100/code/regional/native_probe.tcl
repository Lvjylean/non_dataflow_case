# Read-only, bounded native discovery from the user's routed checkpoint.
if {[catch {
lassign $argv input out driver
file mkdir $out
source [file join [file dirname [info script]] core.tcl]
source [file join [file dirname [info script]] regional.tcl]
open_checkpoint $input
set started [clock milliseconds]
set plan [rf::discover $out {} [list $driver]]
rf::require [expr {[llength [dict get $plan roots]] == 1}] "Expected one spatial broadcast candidate"
set root [lindex [dict get $plan roots] 0]
rf::validate_tree $root
set f [open $out/plan.tcl w]; puts $f [list set regional_plan $plan]; close $f
set f [open $out/summary.txt w]
puts $f "READ_ONLY_PASS"
puts $f "original_fanout=[llength [dict get $root sinks]]"
puts $f "source_branches=[llength [dict get $root frontier]]"
puts $f "added_luts=[dict get $plan lut_added]"
puts $f "source_position=[dict get $root source]"
puts $f "discovery_ms=[expr {[clock milliseconds]-$started}]"
close $f
close_design
exit
} message options]} {
puts stderr [dict get $options -errorinfo]
exit 1
}
