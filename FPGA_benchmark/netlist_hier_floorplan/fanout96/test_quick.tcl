namespace eval f96 {}
source [file dirname [info script]]/quick.tcl
proc f96::plain_names {objects} {return $objects}
set a [dict create driver_name root/Q ref FDRE sinks {b/D a/D}]
set b [dict create driver_name second/O ref LUT2 sinks {c/D}]
set c [dict replace $a sinks {a/D b/D}]
if {[f96::residual_signature [list $a $b]] ne [f96::residual_signature [list $b $c]]} {
    error "Enumeration order must not prevent no-progress detection"
}
set c [dict replace $a sinks {a/D replacement/D}]
if {[f96::residual_signature [list $a]] eq [f96::residual_signature [list $c]]} {
    error "Equal fanout counts with different sinks must not trigger early stop"
}
set c [dict replace $a driver_name replica/Q]
if {[f96::residual_signature [list $a]] eq [f96::residual_signature [list $c]]} {
    error "A new native driver must remain eligible for refinement"
}
set ::created_cells {}; set ::created_nets {}
proc create_cell {option ref names} {
    if {$option ne "-reference" || $ref ne "LUT1" || [llength $names] > 128} {error "Invalid cell batch"}
    lappend ::created_cells {*}$names
}
proc create_net {names} {
    if {[llength $names] > 128} {error "Unbounded net batch"}
    lappend ::created_nets {*}$names
}
proc get_cells {names} {return $::created_cells}
proc get_nets {names} {return $::created_nets}
set names {}; set nets {}
for {set i 0} {$i < 257} {incr i} {lappend names helper_$i; lappend nets helper_${i}_out}
f96::fast_create $names $nets
if {$::created_cells ne $names || $::created_nets ne $nets} {error "Batch boundary lost or repeated an object"}
puts "PASS: residual identity tolerates order, detects changed sinks/replicas, and creation preserves all 257 names across bounded batches"
