source [file join [file dirname [info script]] core.tcl]
foreach name {canonical pin loads drivers values} {rename sb::$name sb::native_$name}
set promoted 0
set driver_queries 0
set connected {original/I0 existing/I0}
proc sb::canonical {p} {
    if {$p eq "ff/C"} {return clock_root}
    if {$p eq "unknown/I0"} {return unknown_root}
    if {$p eq "ground/R"} {return {<const0>_1}}
    if {$p eq "power/CE"} {return {<const1>_1}}
    if {$p eq "fake/R"} {return {<const0>_fake}}
    return [expr {$::promoted ? "promoted_root" : "nested/original_root"}]
}
proc sb::pin {p} {return $p}
proc sb::loads {p} {return [lsort $::connected]}
proc sb::drivers {p} {
    incr ::driver_queries
    if {$p in {unknown/I0 fake/R}} {return {unknown_driver/O}}
    return {{nested/state_reg[51]/Q}}
}
proc sb::values {prop objects} {
    if {$prop eq "NAME"} {return $objects}
    return [lrepeat [llength $objects] 0]
}
proc get_nets {args} {
    if {"-of_objects" in $args} {return [lindex $args end]}
    return {nested/original_root}
}
proc connect_net {args} {
    lappend ::connected [lindex $args end]
    set ::promoted 1
}
proc disconnect_net {args} {
    set index [lsearch -exact $::connected [lindex $args end]]
    if {$index < 0} {error "Missing simulated load"}
    set ::connected [lreplace $::connected $index $index]
}
proc get_property {prop objects} {
    if {$prop eq "TYPE"} {
        if {$objects eq "ground/R"} {return GROUND}
        if {$objects eq "power/CE"} {return POWER}
        return WIRE
    }
    return $objects
}
sb::unlock_net original/I0
sb::connect_input original/I0 copy1/I0
sb::connect_input original/I0 copy2/I0
sb::require [expr {[dict get $sb::track nested/original_root added] eq {copy1/I0 copy2/I0}}] \
    "The second copy was lost after top-segment promotion"
set calls $driver_queries
sb::connect_input original/I0 copy3/I0
sb::require [expr {$driver_queries == $calls}] "Alias resolution repeated the driver query"
sb::rewire copy1/I0 ce_copy_output
sb::require [expr {[dict get $sb::track nested/original_root removed] eq {copy1/I0}}] \
    "Removal from a promoted signal was lost"
set expected [concat [dict get $sb::track nested/original_root before] [dict get $sb::track nested/original_root added]]
set expected [lreplace $expected [lsearch -exact $expected copy1/I0] [lsearch -exact $expected copy1/I0]]
sb::require [expr {[lsort $expected] eq {copy2/I0 copy3/I0 existing/I0 original/I0}}] "Unexpected tracked load set"
sb::unlock_net ff/C 0
set calls $driver_queries
sb::require [expr {[sb::tracking_key ff/C] eq "" && $driver_queries == $calls}] "Clock tracking traversed global drivers"
sb::require [catch {sb::tracking_key unknown/I0}] "Unknown ordinary signal must fail closed"
set calls $driver_queries
sb::require [expr {[sb::tracking_key ground/R] eq ""}] "Renamed ground net must retain constant exclusion"
sb::require [expr {[sb::tracking_key power/CE] eq ""}] "Renamed power net must retain constant exclusion"
sb::require [expr {$driver_queries == $calls}] "Constant alias resolution traversed global drivers"
sb::require [catch {sb::tracking_key fake/R}] "A constant-looking name must not exempt an ordinary signal"
sb::reset_edit_state
sb::require [expr {[array size sb::tracked_net_keys] == 0 && [array size sb::tracked_driver_keys] == 0}] "Stale aliases survived reset"
puts "PASS: promoted hierarchy, repeated copies, rewired copy inputs, cached aliases, clock/constant exclusion, native type instead of constant names, fail-closed unknown signals and reset"
