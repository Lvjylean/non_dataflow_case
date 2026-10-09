namespace eval f96 {}
proc f96::plain_names {x} {return $x}
source [file join [file dirname [info script]] boundary.tcl]
set ::leaves {a/u0/r/D a/u1/r/D}
set ::inputs {a/d a/u0/d a/u1/d}
set ::outputs {}
set ::source root/Q
proc get_pins {args} {
    if {"-filter" in $args} {
        set filter [lindex $args end]
        if {[string match {*IS_LEAF == 1*} $filter]} {return $::leaves}
        if {[string match {*DIRECTION != IN*} $filter]} {return $::outputs}
        return $::inputs
    }
    set name [lindex [lindex $args end] 0]
    if {$name eq "reset"} {return {}}
    return $name
}
proc get_ports {args} {return [lindex $args end]}
proc get_nets {args} {
    if {"-segments" in $args} {return {top a/net a/u0/net a/u1/net}}
    set pin [lindex $args end]
    return [file dirname $pin]/net
}
proc get_property {key object} {return $object}
set groups {n0 {a/u0/r/D} n1 {a/u1/r/D}}
set p [boundary::prepare root/Q $groups]
if {[dict get $p boundaries] != 2 || [dict get $p covered_leaves] != 2} {error "Mixed parent selection failed"}
set ::outputs {a/u0/y}
set p [boundary::prepare reset $groups]
if {[dict get $p boundaries] != 1 || [dict get $p covered_leaves] != 1} {error "Feed-through or port-source guard failed"}
set ::outputs {}
set p [boundary::prepare a/u0/root/Q $groups]
if {[dict get $p boundaries] != 1} {error "Source-containing boundary was selected"}
if {![catch {boundary::prepare root/Q {n0 {a/u0/r/D}}}]} {error "Partial leaf scope accepted"}
if {![catch {boundary::prepare root/Q {n0 {a/u0/r/D a/u0/r/D}}}]} {error "Duplicate leaf scope accepted"}
set p [boundary::prepare reset {n0 {a/u0/r/D a/u1/r/D}}]
if {[dict get $p boundaries] != 1 || [dict get $p terminals] != 1} {error "Uniform ancestor not compressed"}
puts "PASS port source, mixed/uniform trees, feed-through/source guards and exact scope"
