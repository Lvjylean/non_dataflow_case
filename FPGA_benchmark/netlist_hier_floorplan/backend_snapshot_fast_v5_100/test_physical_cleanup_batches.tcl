# The reference is the frozen complete-union 512-net cleanup, not a reduced scope.
source [file join [file dirname [info script]] physical_eco.tcl]
source [file join [file dirname [info script]] physical_cleanup_reference.tcl]
proc check {value message} {if {!$value} {error $message}}
set scratch [file join [pwd] .test_physical_cleanup_batches_[pid]]
file mkdir $scratch
proc reset_fixture {{count 1100}} {
    set ::ordinary {}
    for {set i 0} {$i < $count} {incr i} {lappend ::ordinary ordinary_$i}
    set ::existing [dict create old_disconnected 1 collateral 1 shared_control 1 \
        clock_root 1 clock_alias 1 clock_nonclock_alias 1 VCC 1 GND 1 outside_supply 1 untouched 1]
    foreach n $::ordinary {dict set ::existing $n 1}
    set ::site_cells [dict create SLICE_X1Y1 {edited_ff collateral_lut} SLICE_X2Y2 {other_ff} SLICE_X3Y3 {}]
    set ::cell_pins [dict create edited_ff {edit_D edit_C edit_CE edit_R} \
        collateral_lut {collateral_I collateral_O} other_ff {other_D other_C}]
    set ::pin_nets [dict create edit_D [concat $::ordinary {shared_control clock_nonclock_alias VCC}] \
        edit_C {clock_root clock_alias clock_nonclock_alias} edit_CE {shared_control} edit_R {GND} \
        collateral_I {collateral shared_control} collateral_O {collateral} \
        other_D [list [lindex $::ordinary 0]] other_C {clock_alias}]
    set ::clock_pins {edit_C other_C}
    set ::overrides {};set ::unrouted {};set ::calls {};set ::query_sizes {}
    set ::fail_call 0;set ::fail_physical 0;set ::hide_net {};set ::unplaces 0
}
proc get_property {key objects} {
    set result {}
    foreach object $objects {
        if {[dict exists $::overrides $object $key]} {
            set value [dict get $::overrides $object $key]
        } elseif {$key eq "NAME"} {set value $object
        } elseif {$key eq "TYPE"} {
            set value [expr {$object in {VCC outside_supply} ? "POWER" : ($object eq "GND" ? "GROUND" : "SIGNAL")}]
        } elseif {$key eq "IS_ROUTE_FIXED"} {set value 0
        } elseif {$key eq "FIXED_ROUTE"} {set value {}
        } elseif {$key eq "LOC"} {set value SLICE_X1Y1
        } elseif {$key eq "BEL"} {set value AFF
        } elseif {$key in {IS_LOC_FIXED IS_BEL_FIXED}} {set value 0
        } elseif {$key eq "PBLOCK"} {set value module0
        } else {error "Unexpected property $key"}
        lappend result $value
    }
    if {[llength $objects] == 1} {return [lindex $result 0]}
    return $result
}
proc get_sites {args} {
    set names [lindex $args end];set result {}
    foreach n $names {if {[dict exists $::site_cells $n]} {lappend result $n}}
    return $result
}
proc get_cells {args} {
    set pos [lsearch -exact $args -of_objects]
    if {$pos >= 0} {
        set result {}
        foreach object [lindex $args [expr {$pos+1}]] {
            if {[dict exists $::site_cells $object]} {set result [concat $result [dict get $::site_cells $object]]
            } elseif {$object eq "edit_D"} {lappend result edited_ff
            } else {error "Unexpected cell source $object"}
        }
        return [lsort -unique $result]
    }
    set result {}
    foreach n [lindex $args end] {if {[dict exists $::cell_pins $n]} {lappend result $n}}
    return $result
}
proc get_pins {args} {
    set pos [lsearch -exact $args -of_objects]
    if {$pos < 0} {return [lindex $args end]}
    set result {}
    foreach c [lindex $args [expr {$pos+1}]] {set result [concat $result [dict get $::cell_pins $c]]}
    return $result
}
proc filter {objects expression} {
    set result {}
    foreach p $objects {
        if {$expression eq {DIRECTION == IN && REF_PIN_NAME == D}} {
            if {$p eq "edit_D"} {lappend result $p}
        } elseif {$expression eq {IS_CLOCK == 1}} {
            if {$p in $::clock_pins} {lappend result $p}
        } elseif {$expression eq {IS_CLOCK == 0}} {
            if {$p ni $::clock_pins} {lappend result $p}
        } else {error "Unexpected filter $expression"}
    }
    return $result
}
proc get_nets {args} {
    set pos [lsearch -exact $args -of_objects]
    if {$pos >= 0} {
        set result {}
        foreach p [lindex $args [expr {$pos+1}]] {set result [concat $result [dict get $::pin_nets $p]]}
        return [lsort -unique $result]
    }
    set result {};set requested [lindex $args end]
    foreach n $requested {if {[dict exists $::existing $n] && $n ne $::hide_net} {lappend result $n}}
    lappend ::query_sizes [llength $requested]
    return $result
}
proc route_design {args} {
    if {$args eq {-unroute -physical_nets}} {
        lappend ::calls [list physical]
        if {$::fail_physical} {return -code error -errorcode {MOCK PHYSICAL} "native physical failure"}
        foreach n {VCC GND outside_supply} {dict set ::unrouted $n 1}
    } elseif {[lrange $args 0 1] eq {-unroute -nets}} {
        set objects [lindex $args 2]
        lappend ::calls [linsert $objects 0 ordinary]
        if {$::fail_call && [llength $::calls] == $::fail_call} {
            return -code error -errorcode {MOCK ORDINARY} "native ordinary failure"
        }
        foreach n $objects {
            check [expr {$n ni {clock_root clock_alias clock_nonclock_alias VCC GND outside_supply untouched}}] "Protected/outside net unrouted: $n"
            check [expr {![dict exists $::unrouted $n]}] "Duplicate ordinary unroute: $n"
            dict set ::unrouted $n 1
        }
    } else {error "Unexpected route_design $args"}
}
proc unplace_cell {cells} {
    incr ::unplaces
    check [dict exists $::unrouted collateral] "Changed-D release skipped complete site cleanup"
    foreach c $cells {dict set ::overrides $c LOC {};dict set ::overrides $c IS_LOC_FIXED 0;dict set ::overrides $c IS_BEL_FIXED 0}
}
proc actions {out} {
    set f [open $out/unroute.tsv];gets $f header;set result {}
    while {[gets $f line] >= 0} {
        lassign [split $line \t] name action
        check [expr {![dict exists $result $name]}] "Duplicate action for $name"
        dict set result $name $action
    }
    close $f
    set canonical {}
    foreach name [lsort [dict keys $result]] {lappend canonical [list $name [dict get $result $name]]}
    return $canonical
}
proc metrics {out} {set f [open $out/cleanup_metrics.tcldict];set result [string trim [read $f]];close $f;return $result}
proc compare_case {root count size} {
    reset_fixture $count
    set sites {SLICE_X1Y1 SLICE_X2Y2 SLICE_X1Y1 SLICE_X3Y3}
    set old {old_disconnected old_disconnected deleted_old clock_alias}
    plg::clean_sites_legacy512 $sites $root/reference $old
    set reference [lsort [dict keys $::unrouted]]
    set reference_actions [actions $root/reference]
    set old_calls [llength $::calls]
    reset_fixture $count
    set ::env(PLG_CLEANUP_BATCH_SIZE) $size
    set result [plg::clean_sites $sites $root/fast $old]
    check [expr {[lsort [dict keys $::unrouted]] eq $reference}] "Route status differs from complete legacy cleanup ($size)"
    check [expr {[actions $root/fast] eq $reference_actions}] "Full action manifest differs ($size)"
    check [dict exists $::unrouted old_disconnected] "Disconnected surviving D net omitted"
    check [dict exists $::unrouted collateral] "Collateral site net omitted"
    check [dict exists $::unrouted outside_supply] "Device-wide physical supplies omitted"
    check [expr {![dict exists $::unrouted clock_alias] && ![dict exists $::unrouted untouched]}] "Clock/unaffected route changed"
    set expected [expr {($count+3+$size-1)/$size}]
    check [expr {[dict get $result ordinary_completed_calls] == $expected}] "Wrong native batching"
    check [expr {[dict get $result ordinary_nets] == $count+3 && [dict get $result clock_aliases] == 3}] "Union accounting differs"
    check [expr {[dict get $result exact_native_queries] == $expected && [dict get $result max_native_collection_size] <= $size}] "Native resolution repeated or unbounded"
    check [expr {[dict get $result physical_constant_completed_calls] == 1}] "Physical constant cleanup count differs"
    check [expr {[dict get $result completed] && [dict get $result stage] eq "complete" && [dict get $result total_ms] >= 0}] "Missing completion/runtime evidence"
    check [expr {[metrics $root/fast] eq $result}] "Persisted cleanup metrics differ"
    return [list $old_calls [llength $::calls]]
}
set failed [catch {
    foreach size {1 512 32768 1048576} {compare_case $scratch/size_$size 1100 $size}
    lassign [compare_case $scratch/historical 324174 32768] old_calls new_calls
    check [expr {$old_calls == 635 && $new_calls == 11}] "Historical 324177-object call reduction differs"
    reset_fixture
    unset ::env(PLG_CLEANUP_BATCH_SIZE)
    check [expr {[plg::cleanup_batch_size] == 32768}] "Default cleanup batch is not bounded 32768"
    foreach value {0 -1 1048577 bad 1.5 {}} {
        set ::env(PLG_CLEANUP_BATCH_SIZE) $value
        check [catch {plg::clean_sites {SLICE_X1Y1} $scratch/invalid_$value}] "Invalid batch size accepted"
        check [expr {![llength $::calls]}] "Mutation occurred with invalid batch size"
    }
    foreach {key value} {IS_ROUTE_FIXED 1 IS_ROUTE_FIXED true IS_ROUTE_FIXED TRUE FIXED_ROUTE {NODE_X1 NODE_X2}} {
        reset_fixture
        set ::env(PLG_CLEANUP_BATCH_SIZE) 32768
        dict set ::overrides old_disconnected $key $value
        check [catch {plg::clean_sites {SLICE_X1Y1} $scratch/fixed_$key {old_disconnected}} message] "Explicit fixed route accepted"
        check [string match {*Affected net has an explicit fixed route: old_disconnected} $message] "Original fixed-route failure changed"
        check [expr {![llength $::calls]}] "Fixed-route protection happened after mutation"
    }
    reset_fixture
    dict set ::overrides VCC IS_ROUTE_FIXED true
    check [catch {plg::clean_sites {SLICE_X1Y1} $scratch/fixed_supply}] "Fixed supply accepted"
    check [expr {![llength $::calls]}] "Fixed supply mutation"
    reset_fixture
    set ::env(PLG_CLEANUP_BATCH_SIZE) 600
    set ::fail_call 2
    check [catch {plg::clean_sites {SLICE_X1Y1} $scratch/native_failure {old_disconnected}} message options] "Native ordinary error swallowed"
    check [expr {$message eq "native ordinary failure" && [dict get $options -errorcode] eq {MOCK ORDINARY}}] "Native error/options changed"
    set result [metrics $scratch/native_failure]
    check [expr {![dict get $result completed] && [dict get $result ordinary_started_calls] == 2 && [dict get $result ordinary_completed_calls] == 1 && ![dict get $result physical_constant_started_calls]}] "Native failure did not fail closed"
    check [expr {[llength $::calls] == 2}] "Failed native batch retried or broadened"
    reset_fixture
    set ::fail_physical 1
    check [catch {plg::clean_sites {SLICE_X1Y1} $scratch/physical_failure} message options] "Native physical error swallowed"
    check [expr {[dict get $options -errorcode] eq {MOCK PHYSICAL}}] "Physical error options changed"
    set result [metrics $scratch/physical_failure]
    check [expr {![dict get $result completed] && [dict get $result physical_constant_started_calls] == 1 && ![dict get $result physical_constant_completed_calls]}] "Physical error completion misreported"
    reset_fixture
    set ::hide_net ordinary_10
    check [catch {plg::clean_sites {SLICE_X1Y1} $scratch/missing} message] "Missing exact object accepted"
    check [expr {![llength $::calls]}] "Missing native object mutated routing"
    reset_fixture 0
    dict set ::site_cells SLICE_X1Y1 {}
    plg::clean_sites {SLICE_X1Y1} $scratch/empty {deleted_old}
    check [expr {![llength $::calls] && [dict get [metrics $scratch/empty] completed]}] "Empty/deleted scope routed"
    reset_fixture 10
    set ::env(PLG_CLEANUP_BATCH_SIZE) 32768
    set capture [plg::capture {edit_D} $scratch/release_capture]
    check [expr {[dict size [dict get $capture ff]] == 1}] "Changed-D capture lost FF"
    plg::release $capture
    check [expr {$::unplaces == 1 && [get_property LOC edited_ff] eq ""}] "Changed-D FF release changed"
    reset_fixture 10
    dict set ::overrides collateral_lut IS_LOC_FIXED true
    set state [dict create illegal_sites SLICE_X1Y1 placement_errors 1]
    check [catch {plg::repair_sites $state $scratch/locked_collateral}] "Fixed collateral lock bypassed"
    check [expr {![llength $::calls] && !$::unplaces}] "Collateral protection happened after mutation"
    puts "PASS: full affected union/clock/supply equivalence; 634 to 10 ordinary calls; bounded collections; original native errors; changed-D release and fixed collateral"
} message options]
unset -nocomplain ::env(PLG_CLEANUP_BATCH_SIZE)
file delete -force $scratch
if {$failed} {return -options $options $message}
