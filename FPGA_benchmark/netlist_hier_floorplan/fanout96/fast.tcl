# Batched, cycle-preserving ECO. Source after core.tcl.
# Keep the reference grouping and exhaustive branch/root checks; remove repeated
# scans of the original high-fanout net and transient root-to-helper rewiring.
rename f96::apply f96::apply_reference

proc f96::plain_names {objects} {
    set names [values NAME $objects]
    if {![llength $names]} {return {}}
    # Materialize independent Tcl strings; do not retain scalar views into a
    # large native property collection while building dictionaries and trees.
    set plain [split [join $names \n] \n]
    if {[llength $plain] != [llength $names]} {error "Newline in a netlist object name"}
    return $plain
}

proc f96::pin_objects {names} {
    # Native APIs may shimmer a shared Tcl list into a PIN collection. Give
    # them an independent list so cached planning names remain plain strings.
    if {![llength $names]} {return {}}
    set copy [split [join $names \n] \n]
    return [get_pins $copy]
}

proc f96::fast_plan {before} {
    variable target; variable serial; variable created; variable max_new_luts
    variable cr; variable slr
    set frontier $before; set plan {}; set level 0
    while {[llength $frontier] > $target} {
        set next {}; set covered {}
        foreach entry [groups $frontier $level] {
            lassign $entry hint group
            if {$created >= $max_new_luts} {error "Identity LUT budget exhausted"}
            set name f96_identity_[incr serial]
            if {[regexp {^(SLR[0-9]+)/(.+)$} $hint unused sr region]} {
                set cr($name) $region; set slr($name) $sr
            } elseif {[regexp {^SLR[0-9]+$} $hint]} {set slr($name) $hint}
            lappend plan [list $name $level $hint $group]
            lappend next $name/I0
            foreach p $group {lappend covered $p}
            incr created
        }
        if {[lsort $covered] ne [lsort $frontier]} {error "Planned frontier coverage mismatch"}
        if {[llength $next] >= [llength $frontier]} {error "Tree planning did not progress"}
        set frontier $next; incr level
    }
    return [list $plan $frontier $level]
}

proc f96::fast_disconnect {before_names driver} {
    # Keep cached mappings as names: retaining thousands of individual native
    # object handles makes subsequent Vivado edits and queries very expensive.
    set large [expr {[llength $before_names] > 4096}]
    if {$large} {phase "disconnect_mapping_begin loads=[llength $before_names]"}
    set pairs {}; set covered {}
    set net_names [plain_names [get_nets -quiet -segments -of_objects $driver]]
    foreach name $net_names {
        set members {}
        foreach p [plain_names [get_pins -quiet -of_objects [get_nets [list $name]] -filter {DIRECTION == IN && IS_LEAF == 1}]] {
            lappend members $p; lappend covered $p
        }
        if {[llength $members]} {lappend pairs [list $name $members]}
    }
    if {[lsort $covered] ne [lsort $before_names]} {error "Original segment coverage mismatch"}
    if {$large} {phase "disconnect_mapping_end segments=[llength $pairs]"}
    foreach pair $pairs {
        lassign $pair name members
        for {set i 0} {$i < [llength $members]} {incr i 512} {
            disconnect_net -net [get_nets [list $name]] -pinlist [pin_objects [lrange $members $i [expr {$i+511}]]]
        }
    }
    if {$large} {phase disconnect_commands_end}
}

proc f96::fast_connect {plan frontier root} {
    # Bound live native handles. -dict still receives real objects, acquired
    # immediately before each bounded batch and released before the next.
    set pairs {}
    foreach entry $plan {
        lassign $entry name level hint group
        if {[llength $pairs] + 2 * (1 + [llength $group]) > 1024} {
            connect_net -hierarchical -dict $pairs
            set pairs {}
        }
        set net [get_nets [list ${name}_out]]
        lappend pairs $net [get_pins [list $name/O]]
        foreach p [pin_objects $group] {lappend pairs $net $p}
    }
    if {[llength $pairs]} {connect_net -hierarchical -dict $pairs; set pairs {}}
    # The final root has at most target loads and does not need transient edges.
    foreach p [pin_objects $frontier] {lappend pairs $root $p}
    if {[llength $pairs]} {connect_net -hierarchical -dict $pairs}
}

proc f96::fast_protect {net_names} {
    # Bound property update collections as well as connection edits.
    for {set i 0} {$i < [llength $net_names]} {incr i 128} {
        set_property DONT_TOUCH true [get_nets [lrange $net_names $i [expr {$i+127}]]]
    }
}

proc f96::fast_regions {plan} {
    set buckets [dict create]
    foreach entry $plan {
        lassign $entry name level hint group
        dict lappend buckets $hint $name
    }
    dict for {hint names} $buckets {
        if {[regexp {^(SLR[0-9]+)/(.+)$} $hint unused sr region]} {
            set pb f96_$region
            if {![llength [get_pblocks -quiet $pb]]} {
                create_pblock $pb
                resize_pblock [get_pblocks $pb] -add CLOCKREGION_${region}:CLOCKREGION_${region}
                set_property IS_SOFT true [get_pblocks $pb]
            }
            add_cells_to_pblock [get_pblocks $pb] [get_cells $names]
        } elseif {[regexp {^SLR[0-9]+$} $hint]} {
            add_cells_to_pblock [slr_pblock $hint] [get_cells $names]
        }
    }
}

proc f96::fast_create {names net_names} {
    foreach name $names {create_cell -reference LUT1 $name}
    foreach name $net_names {create_net $name}
}

proc f96::apply {selected directory} {
    variable target; variable created
    file mkdir $directory
    set f [open $directory/application.tsv w]
    puts $f "driver\tref\tbefore\tafter\tnew_luts\tlevels\tcoverage"
    set bf [open $directory/branches.tsv w]
    puts $bf "cell\troot\tlevel\thint\tloads"
    set original [open $directory/original_sinks.tcllist.tsv w]
    puts $original "driver\tsinks_tcl_list"
    set ef [open $directory/new_edges.tcllist.tsv w]
    puts $ef "helper\tsinks_tcl_list"
    set tf [open $directory/per_driver_runtime.tsv w]
    puts $tf "driver\tsinks\thelpers\tplan_ms\tcreate_ms\tdisconnect_ms\tconnect_ms\tverify_ms\tregions_ms\ttotal_ms"
    set count 0
    foreach item $selected {
        set started [clock milliseconds]
        set driver [dict get $item driver]
        set before_names [lsort [plain_names [dict get $item sinks]]]
        if {[lsort [plain_names [loads $driver]]] ne $before_names} {error "Stale discovery: $driver"}
        puts $original "$driver\t[list $before_names]"; flush $original
        set root [get_nets -of_objects $driver]
        if {[llength $root] != 1} {error "Expected one direct driver net"}
        set owned_inputs {}
        foreach p $before_names {
            if {[regexp {^(f96_identity_[0-9]+)/I0$} $p unused owner]} {lappend owned_inputs $owner}
        }
        if {[llength $owned_inputs]} {
            set_property DONT_TOUCH false [get_nets -segments -of_objects $driver]
            set_property DONT_TOUCH false [get_cells $owned_inputs]
        }
        lassign [fast_plan $before_names] plan frontier levels
        set planned [clock milliseconds]
        set names {}; set net_names {}
        foreach entry $plan {
            set name [lindex $entry 0]
            lappend names $name; lappend net_names ${name}_out
        }
        if {[llength [get_cells -quiet $names]] || [llength [get_nets -quiet $net_names]]} {error "Helper collision"}
        fast_create $names $net_names
        set cells [get_cells $names]
        set_property INIT 2'h2 $cells
        set_property DONT_TOUCH true $cells
        set built [clock milliseconds]
        fast_disconnect $before_names $driver
        set disconnected [clock milliseconds]
        fast_connect $plan $frontier $root
        set edges [dict create]
        foreach entry $plan {
            lassign $entry name level hint group
            dict set edges $name/I0 $group
        }
        set connected [clock milliseconds]
        if {[llength $before_names] > 4096} {phase "connect_end loads=[llength $before_names]"}
        # Full readback is intentionally retained for every branch and root.
        foreach entry $plan {
            lassign $entry name level hint group
            if {[lsort [plain_names [loads [get_pins [list $name/O]]]]] ne [lsort $group]} {
                error "Branch connectivity mismatch: $name"
            }
            puts $bf "$name\t$driver\t$level\t$hint\t[llength $group]"
            puts $ef "$name\t[list $group]"
        }
        if {[llength $before_names] > 4096} {phase verify_branches_end}
        if {[lsort [plain_names [loads $driver]]] ne [lsort $frontier]} {error "Root connectivity mismatch: $driver"}
        if {[llength $before_names] > 4096} {phase verify_root_readback_end}
        set pending [plain_names [pin_objects $frontier]]; set recovered {}
        while {[llength $pending]} {
            set next {}
            foreach p $pending {
                if {[string match {f96_identity_*/I0} $p] && [dict exists $edges $p]} {
                    foreach child [plain_names [pin_objects [dict get $edges $p]]] {lappend next $child}
                } else {lappend recovered $p}
            }
            set pending $next
        }
        if {[lsort $recovered] ne $before_names} {error "Original sink coverage mismatch"}
        if {[llength $before_names] > 4096} {phase verify_root_and_coverage_end}
        fast_protect [plain_names [get_nets -segments -of_objects [get_pins -of_objects $cells -filter {DIRECTION == OUT}]]]
        if {[llength $before_names] > 4096} {phase protect_outputs_end}
        fast_protect [plain_names [get_nets -segments -of_objects $driver]]
        if {[llength $before_names] > 4096} {phase protect_root_end}
        if {[llength $owned_inputs]} {set_property DONT_TOUCH true [get_cells $owned_inputs]}
        set verified [clock milliseconds]
        fast_regions $plan
        set finished [clock milliseconds]
        puts $f "$driver\t[dict get $item ref]\t[llength $before_names]\t[llength $frontier]\t[llength $plan]\t$levels\tEXACT_PASS"
        puts $tf "$driver\t[llength $before_names]\t[llength $plan]\t[expr {$planned-$started}]\t[expr {$built-$planned}]\t[expr {$disconnected-$built}]\t[expr {$connected-$disconnected}]\t[expr {$verified-$connected}]\t[expr {$finished-$verified}]\t[expr {$finished-$started}]"
        flush $f; flush $bf; flush $tf
        incr count
        if {$count % 25 == 0} {phase "fast_applied=$count/[llength $selected] helpers=$created"}
    }
    foreach channel [list $f $bf $original $ef $tf] {close $channel}
    return $created
}

proc f96::required {selected} {
    # 96 is a construction margin; the user's acceptance is strictly <100.
    set result {}
    foreach item $selected {
        if {[llength [dict get $item sinks]] >= 100} {lappend result $item}
    }
    return $result
}
