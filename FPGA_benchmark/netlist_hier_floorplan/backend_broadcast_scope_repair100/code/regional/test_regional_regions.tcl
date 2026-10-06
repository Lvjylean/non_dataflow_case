source [file join [file dirname [info script]] core.tcl]
source [file join [file dirname [info script]] regional.tcl]
proc assert {value message} {if {![uplevel 1 [list expr $value]]} {error $message}}
array set properties {}; array set cells {}
proc get_pblocks {args} {
    set result {}; foreach name [lindex $args end] {if {[info exists ::properties($name,IS_SOFT)]} {lappend result $name}}; return $result
}
proc create_pblock {name} {set ::properties($name,IS_SOFT) 1; set ::properties($name,EXCLUDE_PLACEMENT) 0; set ::cells($name) {}; return $name}
proc resize_pblock {pb option ranges} {set ::properties($pb,GRID_RANGES) $ranges}
proc get_cells {args} {if {[lsearch -exact $args -of_objects] >= 0} {return $::cells([lindex $args end])}; return [lindex $args end]}
proc add_cells_to_pblock {pb names} {lappend ::cells($pb) {*}$names}
proc get_property {property objects} {
    if {$property eq "NAME"} {return $objects}
    return $::properties($objects,$property)
}
proc set_property {property value objects} {
    foreach object $objects {
        set ::properties($object,$property) $value
        if {$property eq "EXCLUDE_PLACEMENT"} {set ::properties($object,IS_SOFT) 1}
    }
}
set node [dict create name rfd_lut_1 regions X3Y9]
rf::bind $node
set plan [dict create roots [list [dict create nodes [list $node]]]]
set out [file join [pwd] regional_constraint_test_[pid]]
rf::region_constraints $plan $out
set_property EXCLUDE_PLACEMENT false [get_pblocks rfd_region_X3Y9]
assert {[catch {rf::region_constraints $plan $out} message] && [string match {Regional Pblock must be hard*} $message]} "Soft boundary accepted"
rf::region_constraints $plan $out 1
assert {![sb::one_bit [get_property IS_SOFT rfd_region_X3Y9]]} "Resume did not restore hard constraint"
set ::cells(rfd_region_X3Y9) {}
assert {[catch {rf::region_constraints $plan $out 1} message] && [string match {Regional Pblock membership mismatch*} $message]} "Missing member silently repaired"
file delete -force $out
puts "PASS: native property side effect modeled, creation order, soft rejection, bounded resume repair, exact membership guard"
