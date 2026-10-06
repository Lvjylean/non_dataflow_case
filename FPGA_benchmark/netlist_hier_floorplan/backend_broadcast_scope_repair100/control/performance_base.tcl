source [file join [file dirname [info script]] performance_common.tcl]
source [file join [file dirname [info script]] ../boundary.tcl]
proc f96::fast_disconnect_reference {before_names driver} {
    set pairs {}; set covered {}
    set net_names [perf::timed disconnect_segments {plain_names [get_nets -quiet -segments -of_objects $driver]}]
    foreach name $net_names {
        set members [perf::timed disconnect_mapping {
            plain_names [get_pins -quiet -of_objects [get_nets [list $name]] -filter {DIRECTION == IN && IS_LEAF == 1}]
        }]
        if {[llength $members]} {lappend pairs [list $name $members]; lappend covered {*}$members}
    }
    if {[lsort $covered] ne [lsort $before_names]} {error "Original segment coverage mismatch"}
    foreach pair $pairs {lassign $pair name members; perf::disconnect_segment $name $members}
}
proc f96::fast_disconnect {before_names driver plan} {
    set ::boundary::active 0
    if {!$::boundary::enabled} {fast_disconnect_reference $before_names $driver; return}
    array set original {}; foreach pin $before_names {set original($pin) 1}
    set groups {}
    foreach entry $plan {
        lassign $entry name level hint group
        set leaves {}; foreach pin $group {if {[info exists original($pin)]} {lappend leaves $pin}}
        if {[llength $leaves]} {lappend groups ${name}_out $leaves}
    }
    set recipe [perf::timed boundary_plan [list boundary::prepare [get_property NAME $driver] $groups]]
    set ::boundary::original [array get original]
    set ::boundary::pairs [dict get $recipe pairs]
    set ::boundary::active 1
    if {[info exists ::boundary::trace]} {
        puts $::boundary::trace "$driver\t[dict get $recipe leaves]\t[dict get $recipe boundaries]\t[dict get $recipe covered_leaves]\t[dict get $recipe terminals]\t[expr {[llength [dict get $recipe disconnect]]/2}]\tboundary"
        flush $::boundary::trace
    }
    foreach {name members} [dict get $recipe disconnect] {perf::disconnect_segment $name $members}
}
proc f96::fast_connect {plan frontier root} {
    if {![info exists ::boundary::active] || !$::boundary::active} {fast_connect_reference $plan $frontier $root; return}
    array set original $::boundary::original
    set pairs $::boundary::pairs
    foreach entry $plan {
        lassign $entry name level hint group
        lappend pairs ${name}_out $name/O
        foreach pin $group {if {![info exists original($pin)]} {lappend pairs ${name}_out $pin}}
    }
    # One native batch contains the helper connections and root frontier.
    # All destinations were disconnected above; pair order is unchanged.
    set root_name [get_property NAME $root]
    foreach pin $frontier {lappend pairs $root_name $pin}
    perf::connect_many $pairs
    unset ::boundary::original ::boundary::pairs
    set ::boundary::active 0
}
proc f96::fast_connect_reference {plan frontier root} {
    set pairs {}
    foreach entry $plan {
        lassign $entry name level hint group
        lappend pairs ${name}_out $name/O
        foreach p $group {lappend pairs ${name}_out $p}
    }
    perf::connect_many $pairs
    set pairs {}; set root_name [get_property NAME $root]
    foreach p $frontier {lappend pairs $root_name $p}
    perf::connect_many $pairs
}
proc f96::fast_create {names net_names} {
    set size $::perf::create_batch
    for {set i 0} {$i < [llength $names]} {incr i $size} {
        perf::timed create_cells [list create_cell -reference LUT1 [lrange $names $i [expr {$i+$size-1}]]]
        perf::timed create_nets [list create_net [lrange $net_names $i [expr {$i+$size-1}]]]
    }
    if {[llength [get_cells $names]] != [llength $names] || [llength [get_nets $net_names]] != [llength $net_names]} {
        error "Batched helper creation incomplete"
    }
}
proc f96::fast_protect {names} {
    for {set i 0} {$i < [llength $names]} {incr i 512} {
        perf::timed protect_native [list set_property DONT_TOUCH true [get_nets [lrange $names $i [expr {$i+511}]]]]
    }
}
rename f96::apply f96::apply_before_performance
proc f96::apply {selected directory} {
    array unset ::perf::calls *
    array unset ::perf::elapsed *
    file mkdir $directory
    set ::boundary::trace [open $directory/boundary_execution.tsv w]
    puts $::boundary::trace "driver\tleaves\tboundaries\tcovered_leaves\tterminals\tdisconnect_segments\tmode"
    set code [catch {apply_before_performance $selected $directory} result options]
    close $::boundary::trace
    unset ::boundary::trace
    perf::save $directory
    if {$code} {return -options $options $result}
    return $result
}
