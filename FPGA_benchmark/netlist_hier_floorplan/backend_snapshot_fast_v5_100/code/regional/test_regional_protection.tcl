source [file join [file dirname [info script]] core.tcl]
source [file join [file dirname [info script]] regional.tcl]
rename sb::values sb::real_values
proc sb::values {property objects} {
    if {$property eq "NAME"} {return $objects}
    set result {}; foreach name $objects {lappend result $::flags($name)}; return $result
}
proc get_nets {names} {return $names}
proc get_cells {names} {return $names}
proc set_property {property value objects} {foreach name $objects {set ::flags($name) $value}}
proc reset_property {property objects} {foreach name $objects {set ::flags($name) ""}}
set names {}
for {set i 0} {$i < 131200} {incr i} {
    set name segment_$i; lappend names $name
    set flags($name) [lindex {true false {}} [expr {$i%3}]]
}
set before [array get flags]
set tick [clock milliseconds]
rf::unlock_nets $names
rf::unlock_nets $names
rf::restore
array set original $before
foreach name $names {if {$flags($name) ne $original($name)} {error "Protection not restored: $name"}}
if {[array size rf::saved_nets] != 131200} {error "Protection deduplication failed"}
rf::reset
if {[array size rf::saved_nets]} {error "Cross-design cache leak"}
puts "LOCAL_PROTECTION_131200_MS [expr {[clock milliseconds]-$tick}]"
puts "PASS: array guards, duplicate visits, true/false/unset restoration, cache lifetime"
