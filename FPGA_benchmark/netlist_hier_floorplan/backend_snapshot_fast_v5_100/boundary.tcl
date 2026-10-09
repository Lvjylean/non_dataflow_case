# Compress only complete, single-destination hierarchy branches. All original
# leaf sets remain the acceptance oracle; mixed branches use local leaf edits.
namespace eval boundary { variable enabled 1 }
proc boundary::prepare {driver groups} {
    array set target {}; array set uniform {}; array set ports {}; array set chosen {}; array set exits {}
    set leaves {}
    foreach {net members} $groups {
        foreach pin $members {
            if {[info exists target($pin)]} {error "Duplicate boundary leaf: $pin"}
            set target($pin) $net; lappend leaves $pin
            set parent [file dirname [file dirname $pin]]
            while {$parent ne "." && $parent ne "/"} {
                if {![info exists uniform($parent)]} {set uniform($parent) $net
                } elseif {$uniform($parent) ne $net} {set uniform($parent) ""}
                set parent [file dirname $parent]
            }
        }
    }
    set source [get_pins -quiet [list $driver]]
    if {![llength $source]} {set source [get_ports -quiet [list $driver]]}
    if {[llength $source] != 1} {error "Ambiguous boundary source: $driver"}
    set segments [get_nets -segments -of_objects $source]
    set actual [f96::plain_names [get_pins -of_objects $segments -filter {IS_LEAF == 1 && DIRECTION == IN}]]
    if {[lsort -unique $actual] ne [lsort $leaves]} {error "Boundary plan must cover all original leaves"}
    # A feed-through output could reach leaves outside the instance prefix.
    # Such boundaries cannot be proven complete using subtree membership alone.
    foreach pin [f96::plain_names [get_pins -of_objects $segments -filter {IS_LEAF == 0 && DIRECTION != IN}]] {
        set exits([file dirname $pin]) 1
    }
    set pins [f96::plain_names [get_pins -of_objects $segments -filter {IS_LEAF == 0 && DIRECTION == IN}]]
    foreach pin $pins {
        set parent [file dirname $pin]
        if {![info exists uniform($parent)] || $uniform($parent) eq ""} {continue}
        if {[info exists exits($parent)]} {continue}
        # Never cut the ancestor containing the source primitive.
        if {[string first "$parent/" $driver] == 0} {continue}
        lappend ports($parent) $pin
    }
    # An ancestor sorts before its descendants; every selected boundary is disjoint.
    foreach parent [lsort [array names ports]] {
        set ancestor [file dirname $parent]; set covered 0
        while {$ancestor ne "." && $ancestor ne "/"} {
            if {[info exists chosen($ancestor)]} {set covered 1; break}
            set ancestor [file dirname $ancestor]
        }
        if {!$covered} {set chosen($parent) $uniform($parent)}
    }
    set replacement {}; set covered_leaves 0
    foreach parent [lsort [array names chosen]] {
        foreach pin [lsort -unique $ports($parent)] {lappend replacement $chosen($parent) $pin}
    }
    foreach pin $leaves {
        set parent [file dirname [file dirname $pin]]; set covered 0
        while {$parent ne "." && $parent ne "/"} {
            if {[info exists chosen($parent)]} {set covered 1; break}
            set parent [file dirname $parent]
        }
        if {$covered} {incr covered_leaves} else {lappend replacement $target($pin) $pin}
    }
    array set by_net {}
    foreach {destination pin} $replacement {
        set net [get_nets -of_objects [get_pins [list $pin]]]
        if {[llength $net] != 1} {error "Ambiguous boundary connection: $pin"}
        lappend by_net([get_property NAME $net]) $pin
    }
    set disconnect {}
    foreach name [lsort [array names by_net]] {lappend disconnect $name $by_net($name)}
    return [dict create pairs $replacement disconnect $disconnect leaves [llength $leaves] \
        boundaries [array size chosen] covered_leaves $covered_leaves terminals [expr {[llength $replacement]/2}]]
}
