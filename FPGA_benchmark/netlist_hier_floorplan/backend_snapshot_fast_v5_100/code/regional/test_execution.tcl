source [file join [file dirname [info script]] core.tcl]
proc assert {value message} {if {![uplevel 1 [list expr $value]]} {error $message}}
foreach p {canonical pin drivers} {rename sb::$p sb::original_$p}
proc sb::pin {name} {return P::$name}
proc sb::canonical {name} {return promoted_root}
proc sb::drivers {name} {return {driver/Q}}
array set graph {h/a/I0 h/net h/b/I0 h/net h2/c/I0 h2/net untouched/I0 untouched_net}
set disconnect_calls 0; set connect_calls 0; set corrupt_names 0
proc get_nets {args} {
    if {"-of_objects" in $args} {
        set p [string range [lindex $args end] 3 end]
        return N::$::graph($p)
    }
    set objects {}
    foreach name [lreverse [lindex $args end]] {lappend objects N::$name}
    return $objects
}
proc get_pins {args} {
    set objects {}
    foreach name [lreverse [lindex $args end]] {lappend objects P::$name}
    if {$::corrupt_names && [llength $objects]} {lset objects 0 P::unrequested/I0}
    return $objects
}
proc get_property {property objects} {
    if {$property eq "TYPE"} {return WIRE}
    assert {$property eq "NAME"} "Unexpected property query"
    set result {}; foreach object $objects {lappend result [string range $object 3 end]}
    if {[llength $objects] == 1} {return [lindex $result 0]}
    return $result
}
proc disconnect_net {args} {
    incr ::disconnect_calls
    set net [string range [lindex $args 1] 3 end]
    foreach object [lindex $args 3] {
        set pin [string range $object 3 end]
        assert {$::graph($pin) eq $net} "Disconnect crossed a local net segment"
        unset ::graph($pin)
    }
}
proc connect_net {args} {
    incr ::connect_calls
    assert {[lindex $args 1] eq "-dict"} "Expected native pair mapping"
    foreach {net pin} [lindex $args 2] {
        set name [string range $pin 3 end]
        assert {![info exists ::graph($name)]} "Pin already connected or repeated"
        set ::graph($name) [string range $net 3 end]
    }
}
execopt::configure fast
set sb::tracked_driver_keys(driver/Q) original_root
set sb::track [dict create original_root [dict create before {h/a/I0 h/b/I0 h2/c/I0 untouched/I0} added {} removed {}]]
sb::rewire_many {h/a/I0 h/b/I0 h2/c/I0} replica_Q
assert {$disconnect_calls == 2 && $connect_calls == 1} "Local segment batching was lost"
assert {$graph(h/a/I0) eq "replica_Q" && $graph(h/b/I0) eq "replica_Q" && $graph(h2/c/I0) eq "replica_Q"} "Incorrect destination mapping"
assert {$graph(untouched/I0) eq "untouched_net"} "Unselected signal changed"
assert {[dict get $sb::track original_root removed] eq {h/a/I0 h/b/I0 h2/c/I0}} "Alias promotion lost tracked removals"
assert {![dict exists $sb::track promoted_root]} "Tracking key drifted to the alias"

# Multiple destinations with deliberately reversed native collection order.
execopt::connect_many {net_a a/I0 net_b b/I0 net_a c/I0}
assert {$graph(a/I0) eq "net_a" && $graph(b/I0) eq "net_b" && $graph(c/I0) eq "net_a"} "Native object order changed connectivity"
set before $connect_calls
assert {[catch {execopt::connect_many {net_x dup/I0 net_y dup/I0}}]} "Duplicate pin accepted"
assert {$connect_calls == $before} "Duplicate guard ran after mutation"
set corrupt_names 1
assert {[catch {execopt::connect_many {net_a absent/I0}}]} "Wrong native object with matching count accepted"
assert {$connect_calls == $before} "Name guard ran after mutation"
set corrupt_names 0

set before $disconnect_calls
assert {[catch {sb::rewire_many {h/a/I0 h/a/I0} other_Q}]} "Duplicate rewrite accepted"
assert {$disconnect_calls == $before} "Duplicate rewrite partially changed the graph"
array unset sb::tracked_net_keys *; array unset sb::tracked_driver_keys *
assert {[catch {sb::rewire_many {h/a/I0} other_Q}]} "Unknown ordinary signal accepted"
assert {$disconnect_calls == $before} "Unknown signal was disconnected"

# Bounded chunks, exact coverage and explicit queue lifetime.
set execopt::batch 2
set before $connect_calls
execopt::connect_many {n p0 n p1 n p2 n p3 n p4}
assert {$connect_calls-$before == 3} "Unbounded native connect batch"
set before $connect_calls
execopt::queue_connections queued {q0 q1 q2}
assert {$connect_calls-$before == 2 && ![llength $execopt::pending]} "Queue did not flush at the limit"
execopt::queue_connections queued {later}
assert {![info exists graph(later)]} "Queue changed graph prematurely"
execopt::clear_queues
execopt::flush_connections
assert {![info exists graph(later)]} "Discarded edits survived reset"
puts "PASS: stable alias batch tracking, exact local segments, shuffled native objects, unchanged unselected pins, bounded calls and rejection before mutation"
