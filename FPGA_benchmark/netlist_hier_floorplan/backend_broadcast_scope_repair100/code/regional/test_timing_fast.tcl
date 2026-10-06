source [file join [file dirname [info script]] timing_fast.tcl]
namespace eval sb {}
proc sb::chunks {items n} {
    set out {};for {set i 0} {$i<[llength $items]} {incr i $n} {lappend out [lrange $items $i [expr {$i+$n-1}]]};return $out
}
set out [file join /tmp timing_fast_test_[pid]];file mkdir $out
proc assert {condition message} {if {![uplevel 1 [list expr $condition]]} {error $message}}
set updates 0;set searches 0;set broken 0;set missing 0
set pins [dict create {ff[0]/D} {.4 .1} {ff[1]/CE} {.6 .2} {ff[2]/R} {{} {}}]
proc update_timing {} {incr ::updates}
proc get_pins {args} {
    set result {};foreach p [lreverse [lindex $args end]] {if {$p ne "output_port"} {lappend result $p}}
    if {$::missing} {set result [lrange $result 1 end]}
    return $result
}
proc get_ports {args} {if {[lindex $args end] eq "output_port"} {return output_port};return {}}
proc get_timing_paths {args} {
    incr ::searches
    set kind [lindex $args [expr {[lsearch -exact $args -delay_type]+1}]]
    set objs [lindex $args [expr {[lsearch -exact $args -to]+1}]]
    set result {}
    foreach p $objs {
        set i [expr {$kind eq "max" ? 0 : 1}]
        if {[lindex [dict get $::pins $p] $i] ne ""} {lappend result [list path $p $kind]}
    }
    return $result
}
proc get_property {property objects} {
    set result {}
    foreach obj $objects {
        switch -- $property {
            NAME {set v $obj}
            SETUP_SLACK {set v [lindex [dict get $::pins $obj] 0]}
            HOLD_SLACK {set v [lindex [dict get $::pins $obj] 1]}
            ENDPOINT_PIN {set v [lindex $obj 1]}
            SLACK {set v [lindex [dict get $::pins [lindex $obj 1]] [expr {[lindex $obj 2] eq "max" ? 0 : 1}]]}
            REQUIREMENT {set v 6.5}
            default {error "Unexpected property: $property"}
        }
        lappend result $v
    }
    if {$::broken && $property eq "SETUP_SLACK"} {return {}}
    if {[llength $objects]==1} {return [lindex $result 0]}
    return $result
}
set all [dict keys $pins]
set a [jif::guard_slacks $all $out/fast.tsv]
assert {[dict get $a {ff[0]/D} max]==.4} "Native object order must not change correspondence"
assert {![dict exists $a {ff[2]/R}]} "Missing path must remain absent, not invented as zero"
assert {$searches==2} "Only non-timed endpoints need fallback searches"
set b [jif::path_slacks $all $out/paths.tsv]
foreach p $all {foreach k {max min} {
    assert {[dict exists $a $p $k]==[dict exists $b $p $k]} "Coverage differs"
    if {[dict exists $a $p $k]} {assert {[dict get $a $p $k]==[dict get $b $p $k]} "Slack differs"}
}}
dict set pins {ff[0]/D} {-.25 -.01}
set c [jif::guard_slacks [list {ff[0]/D}] $out/second.tsv]
assert {$updates==2 && [dict get $c {ff[0]/D} max]==-.25} "Old design state cached"
set c [jif::guard_slacks [list {ff[2]/R}] $out/scalar_empty.tsv]
assert {[dict size $c]==0} "Scalar empty property handling"
set c [jif::guard_slacks [list output_port] $out/port.tsv]
assert {[dict size $c]==0} "Port must retain original global-summary coverage"
set missing 1
assert {[catch {jif::guard_slacks $all $out/missing.tsv}]} "Missing endpoint silently accepted"
set missing 0;set broken 1
assert {[catch {jif::guard_slacks $all $out/broken.tsv}]} "Truncated properties silently accepted"
assert {![jif::finite Inf] && ![jif::finite NaN] && ![jif::finite {}]} "Nonfinite values accepted"
file delete -force $out
puts "PASS timing fast: complete coverage, reordered objects, scalar empty, negative slack, no stale cache, fail-closed resolution"
