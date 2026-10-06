# Pure graph work runs outside the Vivado Tcl command wrappers.
if {[catch {
lassign $argv input output min_fanout
source [file join [file dirname [info script]] core.tcl]
source [file join [file dirname [info script]] local_policy.tcl]
source $input
set start [clock milliseconds]
set lb_local [lb::edit_scope [lb::select $lb_snapshot $min_fanout]]
set f [open ${output}.tmp w]
puts $f {set lb_local {}}
dict for {key value} $lb_local {puts $f [list dict set lb_local $key $value]}
close $f; file rename -force ${output}.tmp $output
puts "LOCAL_HOST_PLAN elapsed_ms=[expr {[clock milliseconds]-$start}] replicas=[dict size [dict get $lb_local graph replicas]]"
} message options]} {puts stderr [dict get $options -errorinfo]; exit 1}
