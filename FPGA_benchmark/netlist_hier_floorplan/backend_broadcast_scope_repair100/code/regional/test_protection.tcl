source [file join [file dirname [info script]] core.tcl]
set segment_queries 0
set writes {}
rename sb::canonical sb::native_canonical
rename sb::pin sb::native_pin
rename sb::loads sb::native_loads
rename sb::drivers sb::native_drivers
rename sb::net_at sb::native_net_at
rename sb::values sb::native_values
proc sb::canonical {p} {if {[string match */C $p]} {return clock_root}; return data_root}
proc sb::pin {p} {return $p}
proc sb::net_at {p} {return [expr {$p eq "ff2/C" ? "clock_branch2" : "clock_branch1"}]}
proc sb::loads {p} {return {sink1/D sink2/D}}
proc sb::drivers {p} {return {source/Q}}
proc get_nets {args} {
    if {"-segments" in $args} {incr ::segment_queries; return {data_root data_branch}}
    if {"-of_objects" in $args} {return [sb::net_at [lindex $args end]]}
    return [lindex $args end]
}
proc sb::values {prop objects} {
    if {$prop eq "NAME"} {return $objects}
    set flags {}
    foreach n $objects {lappend flags [expr {$n in {data_root clock_branch2} ? "1" : ""}]}
    return $flags
}
proc set_property {prop value objects} {lappend ::writes [list $prop $value $objects]}
sb::unlock_net ff/C 0
sb::unlock_net ff/C 0
sb::unlock_net ff2/C 0
sb::require [expr {$segment_queries == 0}] "Clock/constant inputs must not traverse global segments"
sb::require [expr {[llength $writes] == 1 && [lindex [lindex $writes 0] 2] eq "clock_branch2"}] "Only the protected local clock branch may be unlocked"
sb::unlock_net source/Q
sb::unlock_net source/Q
sb::require [expr {$segment_queries == 1}] "Ordinary signal segments must only be examined once"
sb::require [expr {[llength $writes] == 2 && [lindex [lindex $writes 1] 2] eq "data_root"}] "Unprotected branch must remain untouched"
sb::require [expr {[dict get $sb::track data_root before] eq {sink1/D sink2/D}}] "Load tracking must survive the protection cache"
sb::require [expr {[array size sb::protected_net_seen] == [dict size $sb::protect_nets]}] "Protection index and saved values differ"
set saved_writes $writes
set saved_protection $sb::protect_nets
sb::reset_edit_state
set writes {}
sb::unlock_net ff/C 0
sb::unlock_net ff2/C 0
sb::unlock_net source/Q
sb::require [expr {$writes eq $saved_writes && $sb::protect_nets eq $saved_protection}] "New edit inherited stale protection state"
puts "PASS: bounded global input protection, per-segment clock keys, batched writes, deduplicated ordinary tracking"
