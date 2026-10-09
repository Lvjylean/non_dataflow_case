# Query-cache lifetime and exact core-helper equivalence use a read-only native
# object model. No Vivado process or production design is modified by this test.
set here [file dirname [file normalize [info script]]]
source $here/code/regional/core.tcl
array set props {}; array set connected {}; array set segments {}; array set pins_by_cell {}; array set pins_by_net {}
array set native_calls {}
proc check {ok why} {if {!$ok} {error $why}}
proc hit {name} {incr ::native_calls($name)}
proc get_property {property objects} {
    hit property_$property
    if {$property eq "OPAQUE_COLLECTION" && [info exists ::required_native_collection] && $objects ne $::required_native_collection} {
        error "Native collection was reconstructed"
    }
    set values {}
    foreach object $objects {
        if {$property eq "CLASS"} {
            set class [lindex [split $object :] 0]
            if {$object eq "same_name"} {set class $::same_name_class}
            lappend values $class
            continue
        }
        if {![info exists ::props($object,$property)]} {error "unknown_property:$property:$object"}
        lappend values $::props($object,$property)
    }
    if {[llength $objects] == 1} {return [lindex $values 0]}
    return $values
}
proc set_property {property value objects} {
    foreach object $objects {set ::props($object,$property) $value}
}
proc get_cells {args} {
    hit cells; set out {}
    foreach name [lindex $args end] {if {[info exists ::props(c:$name,NAME)]} {lappend out c:$name}}
    return $out
}
proc get_pins {args} {
    hit pins; set out {}
    set i [lsearch -exact $args -of_objects]
    if {$i < 0} {
        foreach name [lindex $args end] {if {[info exists ::props(p:$name,NAME)]} {lappend out p:$name}}
    } else {
        foreach object [lindex $args [expr {$i+1}]] {
            if {$object eq "same_name"} {
                if {$::same_name_class eq "cell"} {lappend out p:source/Q} else {lappend out p:other/D p:buffer/I0}
                continue
            }
            if {[info exists ::pins_by_cell($object)]} {lappend out {*}$::pins_by_cell($object)}
            if {[info exists ::pins_by_net($object)]} {lappend out {*}$::pins_by_net($object)}
        }
    }
    set i [lsearch -exact $args -filter]
    if {$i >= 0} {
        set filter [lindex $args [expr {$i+1}]]; set accepted {}
        foreach pin $out {
            if {[string first {DIRECTION == IN} $filter] >= 0 && $::props($pin,DIRECTION) ne "IN"} {continue}
            if {[string first {DIRECTION == OUT} $filter] >= 0 && $::props($pin,DIRECTION) ne "OUT"} {continue}
            lappend accepted $pin
        }
        set out $accepted
    }
    return [lsort -unique $out]
}
proc get_nets {args} {
    hit nets; set out {}
    set i [lsearch -exact $args -of_objects]
    if {$i >= 0} {
        foreach pin [lindex $args [expr {$i+1}]] {lappend out {*}$::connected($pin)}
    } else {set out [lindex $args end]}
    if {[lsearch -exact $args -segments] >= 0} {
        set all {}; foreach net $out {lappend all {*}$::segments($net)}; set out $all
    }
    if {[lsearch -exact $args -top_net_of_hierarchical_group] >= 0} {
        set canonical {};foreach net $out {lappend canonical $::props($net,ROOT)};set out $canonical
    }
    return [lsort -unique $out]
}
proc get_ports {args} {hit ports;return {port:din}}
proc get_sites {args} {hit sites;return site0}
proc get_slrs {args} {hit slrs;return slr0}
proc fixture {} {
    foreach arr {props connected segments pins_by_cell pins_by_net native_calls} {array unset ::$arr *}
    foreach {name ref loc bel init} {source FDRE SLICE_X0Y0 AFF 1'b0 other FDRE SLICE_X0Y1 BFF 1'b0 buffer LUT1 SLICE_X0Y2 A6LUT 2'h2} {
        set obj c:$name
        foreach {property value} [list NAME $name REF_NAME $ref LOC $loc BEL $bel INIT $init DONT_TOUCH true IS_C_INVERTED 0 IS_D_INVERTED 0 IS_R_INVERTED 0] {set ::props($obj,$property) $value}
    }
    set ::props(site0,NAME) SLICE_X0Y0;set ::props(slr0,NAME) SLR0
    set ::props(port:din,NAME) din
    foreach {net type root pinlist} {
        n:data SIGNAL n:data {source/Q OUT other/D IN buffer/I0 IN}
        n:alias SIGNAL n:data {}
        n:clock SIGNAL n:clock {source/C IN other/C IN}
        n:power POWER n:power {source/CE IN}
        n:port SIGNAL n:port {source/D IN}
    } {
        set ::segments($net) [list $net]
        foreach {property value} [list NAME [string range $net 2 end] TYPE $type ROOT $root] {set ::props($net,$property) $value}
        set ::pins_by_net($net) {}
        foreach {pin direction} $pinlist {
            set object p:$pin; lappend ::pins_by_net($net) $object
            foreach {property value} [list NAME $pin DIRECTION $direction] {set ::props($object,$property) $value}
            set ::connected($object) [list $net]
            lappend ::pins_by_cell(c:[file dirname $pin]) $object
        }
    }
    set ::segments(n:data) {n:data n:alias};set ::segments(n:alias) {n:data n:alias}
    vs::clear_legacy
}
proc exercise {} {
    set result {}
    foreach iteration {1 2} {
        foreach pin {source/Q other/D buffer/I0 source/C source/CE source/D} {
            dict set result signal_$pin [sb::signal $pin]
            dict set result net_$pin [sb::net_at $pin]
        }
        dict set result drivers [sb::drivers other/D]
        dict set result loads [sb::loads source/Q]
        dict set result source_config [sb::config source]
        dict set result buffer_config [sb::config buffer]
        dict set result inputs [sb::inputs source]
        dict set result position [sb::position source]
    }
    return $result
}
fixture
set reference [exercise]
set reference_nets $native_calls(nets)
fixture
set actual [vs::with first_stage {exercise}]
check [expr {$actual eq $reference}] helper_equivalence
check [expr {$native_calls(nets)<$reference_nets}] connection_queries_reused
check [expr {[dict get $vs::last_statistics query_hits]>0 && [dict get $vs::last_statistics property_hits]>0}] reused_actual_reads
check [expr {!$vs::active && [array size vs::queries]==0 && [array size vs::properties]==0}] lifetime_ended
# Reopening/placement/ECO must obtain current actual data, including objects
# with identical names. No PASS from the first invocation is consulted.
set props(c:source,INIT) 1'b1;set props(c:source,LOC) SLICE_X0Y9
set connected(p:other/D) n:port
set observed [vs::with changed_stage {
    list [sb::config source] [sb::position source] [sb::signal other/D]
}]
check [expr {[dict get [lindex $observed 0] INIT] eq "1'b1"}] configuration_refreshed
check [expr {[dict get [lindex $observed 1] loc] eq "SLICE_X0Y9"}] placement_refreshed
check [expr {[lindex $observed 2] eq {ports din}}] connectivity_refreshed
# Batch properties feed scalar callers and tolerate valid empty property values.
set props(c:source,FIXED_ROUTE) {};set props(c:other,FIXED_ROUTE) {{route a} {route b}}
vs::begin scalar_vector
set expected [get_property FIXED_ROUTE {c:source c:other}]
set value [vs::property FIXED_ROUTE {c:source c:other}]
check [expr {$expected eq $value}] property_vector_exact
set calls $native_calls(property_FIXED_ROUTE)
check [expr {[vs::property FIXED_ROUTE c:source] eq {} && [vs::property FIXED_ROUTE c:other] eq {{route a} {route b}}}] scalar_from_vector
check [expr {$native_calls(property_FIXED_ROUTE)==$calls}] scalar_did_not_reread
set value [vs::property FIXED_ROUTE {c:other c:source c:other}]
check [expr {$value eq [get_property FIXED_ROUTE {c:other c:source c:other}]}] order_and_duplicate_objects
check [expr {[catch {vs::begin nested} why] && [string first Nested $why]>=0}] nesting_rejected
vs::end
# Preserve the original native collection on complete and partial cache misses.
# Significant input representation stands in for Vivado's opaque collection
# type here; the server regression additionally uses actual Pblock objects.
set props(c:source,OPAQUE_COLLECTION) source
set props(c:other,OPAQUE_COLLECTION) other
vs::begin native_collection
set required_native_collection c:source
check [expr {[vs::property OPAQUE_COLLECTION $required_native_collection] eq "source"}] scalar_collection_kept
set required_native_collection "c:source   c:other"
check [expr {[vs::property OPAQUE_COLLECTION $required_native_collection] eq {source other}}] mixed_collection_kept
set calls $native_calls(property_OPAQUE_COLLECTION)
check [expr {[vs::property OPAQUE_COLLECTION {c:other c:source}] eq {other source}}] cached_collection_order
check [expr {$native_calls(property_OPAQUE_COLLECTION)==$calls}] cached_collection_did_not_read
unset required_native_collection
vs::end
# Outside the context there is no generic query/property memoization.
set before $native_calls(property_INIT)
vs::property INIT c:source;vs::property INIT c:source
check [expr {$native_calls(property_INIT)==$before+2}] default_native_pass_through
# Unknown/missing properties never become synthetic protection defaults or
# cache entries, and a second invocation retains the original native failure.
vs::begin unknown_property
foreach attempt {1 2} {
    check [expr {[catch {vs::property UNKNOWN_PROTECTION c:source} why] && $why eq "unknown_property:UNKNOWN_PROTECTION:c:source"}] unknown_protection_rejected
}
check [expr {$native_calls(property_UNKNOWN_PROTECTION)==2}] unknown_failure_not_cached
check [expr {![info exists vs::properties([list UNKNOWN_PROTECTION [list c c:source]])]}] failed_read_not_published
vs::invalidate unknown_native_change
check [expr {[catch {vs::property INIT c:source} why] && [string first invalidated $why]>=0}] invalidated_read_rejected
vs::end
# Native mutation is stopped before it runs and invalidates all actual evidence.
set before $props(c:source,INIT)
set code [catch {vs::with mutation_guard {
    vs::property INIT c:source
    set_property INIT 1'b0 c:source
}} why]
check [expr {$code && [string first {Mutation is forbidden} $why]>=0 && $props(c:source,INIT) eq $before}] mutation_stopped_before_native
check [expr {!$vs::active && [dict get $vs::last_statistics invalid]}] failure_cleanup
set_property INIT 1'b0 c:source
check [expr {[vs::with new_stage {vs::property INIT c:source}] eq "1'b0"}] fresh_after_failure
check [expr {[catch {vs::query unsupported_custom_query thing} why] && [string first Unsupported $why]>=0}] unknown_query_not_cacheable
# Equal displayed names must not collide across native object classes.
set props(same_name,INIT) cell_init
vs::begin same_name_identity
set same_name_class cell
check [expr {[vs::property INIT same_name] eq "cell_init"}] cell_identity
check [expr {[vs::query get_pins -of_objects same_name] eq {p:source/Q}}] cell_query_identity
set same_name_class net;set props(same_name,INIT) net_init
check [expr {[vs::property INIT same_name] eq "net_init"}] net_identity
check [expr {[vs::query get_pins -of_objects same_name] eq {p:buffer/I0 p:other/D}}] net_query_identity
set same_name_class cell
check [expr {[vs::property INIT same_name] eq "cell_init"}] previous_class_identity
check [expr {[vs::query get_pins -of_objects same_name] eq {p:source/Q}}] previous_query_identity
vs::end
# Cache capacity affects only reuse; every original native operation still runs.
set saved_query_limit $vs::query_limit;set saved_property_limit $vs::property_limit
set vs::query_limit 0;set vs::property_limit 0
vs::begin bounded_cache
set before $native_calls(property_INIT)
vs::property INIT c:source;vs::property INIT c:source
check [expr {$native_calls(property_INIT)==$before+2}] property_capacity_falls_back
set before $native_calls(pins)
vs::query get_pins -of_objects c:source;vs::query get_pins -of_objects c:source
check [expr {$native_calls(pins)==$before+2}] query_capacity_falls_back
set metrics [vs::end]
check [expr {[dict get $metrics budget_bypasses]==4}] budget_bypasses_recorded
set vs::query_limit $saved_query_limit;set vs::property_limit $saved_property_limit
puts "PASS native/core equivalence, per-stage query reuse, property vectors, empty values, config/location/connectivity freshness, no cached failures/PASS, mutation rejection and cleanup"
