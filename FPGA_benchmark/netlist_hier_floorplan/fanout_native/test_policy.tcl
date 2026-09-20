# Offline policy/controller tests; no Vivado executable is called.
source [file dirname [file normalize [info script]]]/core.tcl
proc check {condition message} {if {![uplevel 1 [list expr $condition]]} {error $message}}
set count 0
proc case {name body} {uplevel 1 $body; incr ::count; puts "PASS: $name"}
set out [file join /tmp hf2-policy-[pid]]; file mkdir $out
case property_materialization_preserves_empty_and_scalar_values {
    proc get_property {property objects} {return $::test_values}
    foreach objects {{one} {one two} {one two three}} values [list "" [list "" ""] [list 0 1 CE]] {
        set ::test_values $values
        set expected [expr {[llength $objects] == 1 ? [list $values] : $values}]
        check {[hf2::plain_values MOCK $objects] eq $expected} "Property value shape changed"
    }
    check {[hf2::plain_values MOCK {}] eq {}} "Empty object collection changed"
    rename get_property {}
}
case cascade_names_are_resolved_to_native_objects {
    proc get_pins {args} {
        check {[lindex $args end] eq [list {carry[3]/CI}]} "Pin query lost exact name"
        return native_pin_handle
    }
    proc get_cells {args} {
        check {[lindex $args end] eq "native_pin_handle"} "Plain name passed as native object"
        return native_cell_handle
    }
    proc get_property {property object} {
        if {$property eq "NAME"} {return {carry[3]/CI}}
        return CARRY8
    }
    check {[hf2::sink_kind_values {carry[3]/CI} 0 CI] eq "CASCADE_PIN"} "Cascade protection lost"
    rename get_pins {}
    proc get_pins {args} {return {}}
    check {[catch {hf2::sink_kind_values {carry[3]/CI} 0 CI} message]} "Missing pin silently ignored"
    check {[string match {*cascade candidate pin*} $message]} "Missing pin lacks context"
    foreach command {get_pins get_cells get_property} {rename $command {}}
}
case driver_coverage {
    foreach ref {FD FDCE FDPE FDRE FDSE LUT1 LUT2 LUT3 LUT4 LUT5 LUT6 LUT6_2} {check {[hf2::classify $ref x] eq "NATIVE"} "Native family omitted"}
    foreach ref {RAMB18E2 RAMB36E2 URAM288 URAM288_BASE} {check {[hf2::classify $ref x] eq "MEMORY_IDENTITY"} "Memory family omitted"}
    foreach ref {CARRY4 CARRY8} {check {[hf2::classify $ref x] eq "CARRY_IDENTITY"} "Carry fallback omitted"}
    check {[hf2::classify BUFGCE x] eq "OTHER_IDENTITY"} "Control buffer omitted"
    check {[hf2::classify LUT1 f96_identity_3] eq "OWNED_IDENTITY"} "Helper provenance omitted"
}
case clock_pin_is_not_a_whole_net_exemption {
    check {[hf2::net_status 0 FDRE 1 1 32761] eq "MIXED_CLOCK_DATA"} "Mixed net was excluded"
    check {[hf2::net_status 1 FDRE 1 1 32761] eq "CLOCK_DISTRIBUTION"} "Clock object changed"
    check {[hf2::net_status 0 FDRE 1 10 0] eq "CLOCK_PIN_ONLY"} "Clock-only loads changed"
    check {[hf2::net_status 0 FDRE 2 1 32761] eq "UNSUPPORTED_DRIVER_COUNT"} "Multidriver not retained"
    set rows [list [dict create logical 99 status SELECTED] [dict create logical 100 status MIXED_CLOCK_DATA] [dict create logical 32762 status CLOCK_DISTRIBUTION] [dict create logical NOT_ENUMERATED status CLOCK_DISTRIBUTION]]
    check {[dict get [hf2::acceptance_from_rows $rows] ordinary_ge100] == 2} "Legacy mixed exclusions must not certify PASS"
}
case at_most_one_phys_opt_configuration {
    foreach cfg {{refinement_passes 2} {refinement_passes 3} {native_target 100} {post_place_lut_budget -1} {upstream_levels 2} {local_site_attempts 0}} {
        check {[catch {hf2::configure $cfg}]} "Invalid or unbounded configuration accepted"
    }
    check {[dict get $::hf2::cfg refinement_passes] == 1} "Default must be one"
}
case retained_branches_and_multilevel_exactness {
    foreach target {2 3 7 96} {
        hf2::configure [list memory_target $target]
        foreach n {1 2 3 7 96 100 1024} {
            set pins {}; for {set i 0} {$i < $n} {incr i} {lappend pins sink_$i/D}
            set ::f96::serial 0; set ::f96::created 0
            lassign [hf2::tree_plan $pins 1 0] plan frontier levels
            check {[llength $frontier]+1 <= $target} "Clock/cascade branch was not budgeted at root"
            set graph [dict create]
            foreach entry $plan {
                lassign $entry name level hint group
                check {[llength $group] <= $target} "Branch exceeds logical target"
                dict set graph $name/I0 $group
            }
            set pending $frontier; set actual {}
            while {[llength $pending]} {
                set next {}
                foreach p $pending {if {[dict exists $graph $p]} {lappend next {*}[dict get $graph $p]} else {lappend actual $p}}
                set pending $next
            }
            check {[lsort $actual] eq [lsort $pins]} "Leaf multiset differs"
        }
    }
    check {[catch {hf2::tree_plan {a/D b/D} 96 0}]} "No budget for preserved root branch"
    hf2::configure {memory_target 96}
}
case placed_bucket_order_is_stable_and_keeps_sites_atomic {
    array unset ::hf2::locations; array set ::hf2::locations {}
    set pins {}
    for {set i 0} {$i<250} {incr i} {
        lappend pins cell_$i/D
        set ::hf2::locations(cell_$i) SLICE_X[expr {$i%25}]Y1
    }
    set ::f96::serial 0; set ::f96::created 0
    set first [hf2::tree_plan $pins 0 1]
    set ::f96::serial 0; set ::f96::created 0
    check {[hf2::tree_plan [lreverse $pins] 0 1] eq $first} "Input order changed deterministic site grouping"
    lassign $first plan frontier levels
    set site_owner [dict create]; set covered {}
    foreach entry $plan {
        lassign $entry helper level hint group
        check {[llength $group]<=96} "Helper fanout exceeded target"
        if {$level!=0} {continue}
        foreach pin $group {
            set site [hf2::site_key $pin]
            if {[dict exists $site_owner $site]} {
                check {[dict get $site_owner $site] eq $helper} "Packed site split between drivers"
            }
            dict set site_owner $site $helper
            lappend covered $pin
        }
    }
    check {[lsort $covered] eq [lsort $pins]} "Coverage changed during ordered traversal"
}
# Controller contract uses synthetic inventories and mocked physical operations.
foreach name {scan actions apply_memory apply_residual audit_identities assert_placed_helpers mark_upstream mark_native} {rename hf2::$name hf2::saved_$name}
proc hf2::scan {path {physical 0}} {
    lappend ::trace [list SCAN [file tail $path]]
    switch [file tail $path] {
        before {return [list [dict create ref RAMB36E2 sinks [lrepeat 100 x/D]]]}
        pre_place - post_place - refinement_1 {return [list [dict create ref FDRE sinks [lrepeat 100 x/D]]]}
        post_native {return [list [dict create ref BUFGCE sinks [lrepeat 120 x/D]] [dict create ref CARRY8 sinks [lrepeat 112 y/D]] [dict create ref FDRE sinks [lrepeat 101 z/D]]]}
    }
    return {}
}
proc hf2::actions {items out} {
    set n {}; set m {}; set o {}
    foreach item $items {switch [dict get $item ref] {FDRE {lappend n $item} RAMB36E2 {lappend m $item} default {lappend o $item}}}
    return [list $n $m $o]
}
proc hf2::mark_native {items target out} {lappend ::trace [list REQUEST $target]; return [expr {[llength $items] ? "native_net" : ""}]}
proc hf2::mark_upstream {items out} {lappend ::trace UPSTREAM}
proc hf2::apply_memory {items out} {lappend ::trace PRE_ECO}
proc hf2::apply_residual {items out} {
    set refs {}; foreach i $items {lappend refs [dict get $i ref]}
    check {[lsort $refs] eq [lsort {BUFGCE CARRY8 FDRE}]} "Later non-native/new-generation drivers were dropped"
    lappend ::trace FINAL_ECO
}
proc hf2::audit_identities {out} {lappend ::trace IDENTITY_AUDIT}
proc hf2::assert_placed_helpers {} {lappend ::trace PLACEMENT_AUDIT}
proc get_nets {args} {return [lindex $args end]}
proc place_design {args} {check {$args eq ""} "Unexpected global placer override"; lappend ::trace PLACE}
proc phys_opt_design {args} {check {[lindex $args 0] eq "-force_replication_on_nets"} "Unexpected extra default phys_opt"; lappend ::trace PHYS_OPT}
proc write_checkpoint {path} {lappend ::trace CHECKPOINT}
proc route_design {} {lappend ::trace ROUTE}
case bounded_controller_and_late_dispatch {
    foreach passes {0 1} {
        set ::trace {}; hf2::configure [list refinement_passes $passes]
        file mkdir $out/flow$passes
        hf2::implement $out/flow$passes
        check {[llength [lsearch -all -exact $::trace PLACE]] == 1} "Repeated global placement"
        check {[llength [lsearch -all -exact $::trace PHYS_OPT]] == $passes} "Too many phys_opt calls"
        check {[lsearch -exact $::trace PRE_ECO] < [lsearch -exact $::trace PLACE]} "Preprocessing ran late"
        check {[lsearch -exact $::trace FINAL_ECO] < [lsearch -exact $::trace PLACEMENT_AUDIT]} "Missing post-ECO legality check"
        check {[lsearch -exact $::trace PLACEMENT_AUDIT] < [lsearch -exact $::trace ROUTE]} "Route ran before legality check"
        check {[lsearch -exact $::trace {REQUEST 48}] < 0} "Iterative target halving returned"
    }
}
puts "PASS: $count groups; native execution NOT_RUN"
