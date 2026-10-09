# Native query reuse is restricted to an explicit immutable verification stage.
# No verification decision or PASS result is cached, and no object handle survives
# end/invalidation. Outside a context every call executes its original command.
if {[namespace exists ::vs]} {return}
namespace eval vs {
    variable active 0
    # Native reference mode runs the same checker and guards without reuse.
    variable reuse 1
    variable invalid 0
    variable stage {}
    variable epoch 0
    variable queries; array set queries {}
    variable properties; array set properties {}
    variable counters {}
    variable traced {}
    # Reuse is optional. Bound retained data and fall back to native reads when
    # a large verification stage would exceed the cache budget.
    variable query_limit 16384
    variable query_object_limit 262144
    variable property_limit 262144
    variable retained_query_objects 0
    variable readonly_commands {get_cells get_pins get_nets get_ports get_pblocks get_sites get_slrs get_clock_regions get_clocks}
    variable mutation_commands {create_cell create_net remove_cell remove_net rename_cell rename_net connect_net disconnect_net set_property reset_property create_pblock delete_pblock resize_pblock add_cells_to_pblock remove_cells_from_pblock place_cell unplace_cell place_design phys_opt_design opt_design route_design read_checkpoint open_checkpoint close_design read_xdc link_design create_clock create_generated_clock set_clock_groups set_false_path set_multicycle_path set_max_delay set_min_delay set_input_delay set_output_delay reset_timing}
}
proc vs::clear_legacy {} {
    # Existing helpers retain short-lived caches; explicitly clear them at both
    # lifecycle boundaries so they cannot return an earlier stage's actual data.
    foreach ns {::sb ::rf} {
        foreach name {pin_objects cell_objects positions refs site_slrs site_regions region_slrs ancestor_cache asynchronous} {
            if {[array exists ${ns}::$name]} {array unset ${ns}::$name *}
        }
    }
    if {[info exists ::sb::signal_cache]} {set ::sb::signal_cache {}}
}
proc vs::assert_readable {} {
    variable active; variable invalid
    if {$active && $invalid} {error "Verification context invalidated; begin a fresh stage"}
}
proc vs::begin {name} {
    variable active; variable invalid; variable stage; variable epoch
    variable queries; variable properties; variable counters; variable traced
    variable mutation_commands
    variable retained_query_objects
    if {$active} {error "Nested verification context is forbidden: $stage"}
    if {$name eq ""} {error "Verification stage identity is required"}
    array unset queries *; array unset properties *; clear_legacy
    incr epoch; set stage $name; set invalid 0; set active 1
    set retained_query_objects 0
    set counters [dict create stage $name epoch $epoch reuse $::vs::reuse query_hits 0 query_misses 0 property_hits 0 property_misses 0 native_property_calls 0 native_class_calls 0 typed_identity_objects 0 prefetch_batches 0 prefetch_fallbacks 0 uncached_identity 0 budget_bypasses 0 native_elapsed_us 0]
    set traced {}
    foreach command $mutation_commands {
        set resolved [namespace which -command ::$command]
        if {$resolved ne ""} {
            trace add execution $resolved enter ::vs::mutation_guard
            lappend traced $resolved
        }
    }
    return $epoch
}
proc vs::invalidate {{why explicit_boundary}} {
    variable active; variable invalid; variable queries; variable properties; variable counters
    array unset queries *; array unset properties *; clear_legacy
    if {$active} {set invalid 1; dict set counters invalidated $why}
}
proc vs::mutation_guard {command operation} {
    variable counters
    invalidate [lindex $command 0]
    set message "Mutation is forbidden inside a read-only verification context: [lindex $command 0]"
    dict set counters invalidation_message $message
    error $message
}
proc vs::end {} {
    variable active; variable invalid; variable stage; variable queries; variable properties; variable counters; variable traced
    if {!$active} {error "No active verification context"}
    set result [dict merge $counters [dict create invalid $invalid query_entries [array size queries] property_entries [array size properties]]]
    foreach command $traced {
        if {[namespace which -command $command] ne ""} {trace remove execution $command enter ::vs::mutation_guard}
    }
    set traced {}; array unset queries *; array unset properties *; clear_legacy
    set active 0; set invalid 0; set stage {}
    return $result
}
proc vs::with {name script} {
    begin $name
    set code [catch {uplevel 1 $script} result options]
    set statistics [end]
    set ::vs::last_statistics $statistics
    # Some embedded Tcl builds clear errors raised by execution traces. Keep a
    # diagnostic independently, and reject a caught mutation as well as an
    # uncaught one: invalidated evidence can never produce a successful stage.
    if {[dict get $statistics invalid]} {
        if {[dict exists $statistics invalidation_message]} {set message [dict get $statistics invalidation_message]} else {set message "Verification context invalidated: [dict get $statistics invalidated]"}
        if {!$code || $result eq ""} {return -code error -errorcode {VS INVALID_STAGE} $message}
    }
    if {$code} {return -options $options $result}
    return $result
}
proc vs::query {command args} {return [query_impl {} $command {*}$args]}
proc vs::query_from {native_class command args} {
    # Callers may provide a type only for objects returned by the corresponding
    # native query. Keep the original collection in the command unchanged.
    if {[lsearch -exact $args -of_objects] < 0} {error "Typed verification query requires -of_objects"}
    return [query_impl $native_class $command {*}$args]
}
proc vs::query_impl {native_class command args} {
    variable active; variable reuse; variable queries; variable counters; variable readonly_commands
    variable query_limit; variable query_object_limit; variable retained_query_objects
    set command [namespace tail $command]
    if {$command ni $readonly_commands} {error "Unsupported verification query: $command"}
    assert_readable
    set script [list ::$command {*}$args]
    if {!$active} {return [uplevel #0 $script]}
    if {!$reuse} {
        dict incr counters query_misses
        set tick [clock microseconds]
        set code [catch {uplevel #0 $script} result options]
        dict incr counters native_elapsed_us [expr {[clock microseconds]-$tick}]
        if {$code} {return -options $options $result}
        return $result
    }
    set identity $args
    set index [lsearch -exact $args -of_objects]
    if {$index >= 0 && $index+1 < [llength $args]} {
        # A cell, net, port or Pblock may have the same displayed name. Keep
        # their native classes in the key while passing original objects intact.
        if {[catch {object_identity [lindex $args [expr {$index+1}]] $native_class} typed]} {
            dict incr counters uncached_identity
            return [uplevel #0 $script]
        }
        lset identity [expr {$index+1}] $typed
    }
    set key [list $command $identity]
    if {[info exists queries($key)]} {dict incr counters query_hits; return $queries($key)}
    dict incr counters query_misses
    set tick [clock microseconds]
    set code [catch {uplevel #0 $script} result options]
    dict incr counters native_elapsed_us [expr {[clock microseconds]-$tick}]
    if {$code} {return -options $options $result}
    set count [llength $result]
    if {[array size queries] < $query_limit && $retained_query_objects+$count <= $query_object_limit} {
        set queries($key) $result;incr retained_query_objects $count
    } else {dict incr counters budget_bypasses}
    return $result
}
proc vs::object_identity {objects {native_class {}}} {
    variable counters
    if {$native_class ne ""} {
        if {$native_class ni {cell pin net port pblock site slr clock_region clock}} {error "Unsupported known native class: $native_class"}
        set result {}
        foreach object $objects {lappend result [list $native_class $object]}
        dict incr counters typed_identity_objects [llength $objects]
        return $result
    }
    set tick [clock microseconds]
    dict incr counters native_class_calls
    set code [catch {get_property CLASS $objects} classes options]
    dict incr counters native_elapsed_us [expr {[clock microseconds]-$tick}]
    if {$code} {return -options $options $classes}
    if {[llength $objects] == 1} {set classes [list $classes]}
    if {[llength $objects] != [llength $classes]} {error "Incomplete native object classes"}
    set result {}
    foreach object $objects class $classes {
        if {$class eq ""} {error "Unknown native object class"}
        lappend result [list $class $object]
    }
    return $result
}
proc vs::property {property objects {native_class {}}} {
    variable active; variable reuse; variable properties; variable counters
    variable property_limit
    assert_readable
    if {!$active || ![llength $objects]} {return [get_property $property $objects]}
    if {!$reuse} {
        dict incr counters property_misses [llength $objects]
        dict incr counters native_property_calls
        set tick [clock microseconds]
        set code [catch {get_property $property $objects} result options]
        dict incr counters native_elapsed_us [expr {[clock microseconds]-$tick}]
        if {$code} {return -options $options $result}
        return $result
    }
    if {[catch {object_identity $objects $native_class} identities]} {
        dict incr counters uncached_identity
        return [get_property $property $objects]
    }
    set missing 0
    foreach identity $identities {
        set key [list $property $identity]
        if {[info exists properties($key)]} {dict incr counters property_hits} else {
            dict incr counters property_misses
            set missing 1
        }
    }
    if {$missing} {
        set tick [clock microseconds]
        dict incr counters native_property_calls
        # Vivado collections carry native object types. Rebuilding a subset as
        # a plain Tcl list loses that type for objects such as Pblocks. Query
        # the original collection intact when any member is missing; a mixed
        # hit/miss batch may reread values but never substitutes object names.
        set code [catch {get_property $property $objects} result options]
        dict incr counters native_elapsed_us [expr {[clock microseconds]-$tick}]
        if {$code} {return -options $options $result}
        if {[llength $objects] == 1} {set values [list $result]} else {set values $result}
        # An incomplete native vector must never be filled with cached defaults.
        if {[llength $values] != [llength $objects]} {error "Incomplete native property vector: $property"}
        if {[array size properties]+[llength $objects] > $property_limit} {
            dict incr counters budget_bypasses
            return $result
        }
        foreach identity $identities value $values {set properties([list $property $identity]) $value}
    }
    set result {}
    foreach identity $identities {lappend result $properties([list $property $identity])}
    if {[llength $objects] == 1} {return [lindex $result 0]}
    return $result
}
proc vs::prefetch {properties objects {native_class {}}} {
    foreach property $properties {property $property $objects $native_class}
}
proc vs::save {statistics path} {
    file mkdir [file dirname $path]
    set f [open $path w]; puts $f "metric\tvalue"
    dict for {name value} $statistics {puts $f "$name\t$value"}
    close $f
}
