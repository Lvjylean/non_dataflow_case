# Complete live-net discovery and cycle-preserving spatial identity trees.
# Manual identity edits add no registers or pipeline stages. Vivado may
# separately replicate protected drivers through its native optimization flow.
namespace eval f96 {
    variable target 96
    variable serial 0
    variable max_new_luts 50000
    variable created 0
    variable cr; array set cr {}
    variable slr; array set slr {}
    variable loc; array set loc {}
}
proc f96::values {p objects} {
    if {![llength $objects]} {return {}}
    set v [get_property $p $objects]
    if {[llength $objects] == 1} {return [list $v]}
    return $v
}
proc f96::phase {s} {puts "F96 [clock seconds] $s"; flush stdout}
proc f96::loads {driver} {
    return [lsort -unique [get_pins -quiet -of_objects [get_nets -quiet -segments -of_objects $driver] -filter {DIRECTION == IN && IS_LEAF == 1}]]
}
proc f96::disconnect {group} {
    set wanted [dict create]; foreach p $group {dict set wanted $p 1}
    set pairs {}; set covered {}
    foreach net [get_nets -quiet -of_objects $group] {
        set members {}
        foreach p [get_pins -quiet -of_objects $net -filter {DIRECTION == IN && IS_LEAF == 1}] {
            if {[dict exists $wanted $p]} {lappend members $p}
        }
        if {[llength $members]} {lappend pairs [list $net $members]; set covered [concat $covered $members]}
    }
    if {[lsort $covered] ne [lsort $group]} {error "Sink segment coverage mismatch"}
    foreach pair $pairs {disconnect_net -net [lindex $pair 0] -objects [lindex $pair 1]}
}
proc f96::spatial_cache {} {
    variable cr; variable slr; variable loc
    array set site_cr {}; array set cr_slr {}
    foreach region [get_clock_regions] {
        set rn [get_property NAME $region]
        set cr_slr($rn) [get_property NAME [get_slrs -of_objects $region]]
        foreach sn [values NAME [get_sites -of_objects $region]] {set site_cr($sn) $rn}
    }
    set cells [get_cells -hier -filter {IS_PRIMITIVE == 1}]
    foreach name [values NAME $cells] location [values LOC $cells] {
        if {[info exists site_cr($location)]} {
            set cr($name) $site_cr($location); set slr($name) $cr_slr($cr($name)); set loc($name) $location
        }
    }
}
proc f96::site_of {pin} {
    variable loc
    set name [string range $pin 0 [expr {[string last / $pin]-1}]]
    set original $name
    while {$name ne ""} {
        if {[info exists loc($name)]} {return $loc($name)}
        set slash [string last / $name]
        if {$slash < 0} {break}
        set name [string range $name 0 [expr {$slash-1}]]
    }
    return "UNLOCATED:$original"
}
proc f96::region_of {pin {level 0}} {
    variable cr; variable slr
    set name [string range $pin 0 [expr {[string last / $pin]-1}]]
    while {$name ne ""} {
        if {$level == 0 && [info exists cr($name)]} {return "$slr($name)/$cr($name)"}
        if {[info exists slr($name)]} {return $slr($name)}
        set slash [string last / $name]
        if {$slash < 0} {break}
        set name [string range $name 0 [expr {$slash-1}]]
    }
    return UNKNOWN
}
proc f96::groups {frontier level} {
    variable target
    set buckets [dict create]
    foreach p $frontier {dict lappend buckets [region_of $p $level] $p}
    set result {}
    foreach key [lsort [dict keys $buckets]] {
        set sites [dict create]
        foreach p [dict get $buckets $key] {dict lappend sites [site_of $p] $p}
        set group {}
        foreach site [lsort -dictionary [dict keys $sites]] {
            set atom [lsort [dict get $sites $site]]
            # Preserve already shared CE/reset and LUT input connections at a
            # site. An oversized site is split by pin role before count limiting.
            set atoms [list $atom]
            if {[llength $atom] > $target} {
                set roles [dict create]
                foreach p $atom {
                    set role [lindex [split $p /] end]
                    if {$role in {R S CLR PRE}} {set role SET_RESET}
                    dict lappend roles $role $p
                }
                set atoms [dict values $roles]
            }
            foreach unit $atoms {
                if {[llength $unit] > $target} {error "A shared site/pin-role group exceeds the fanout target: $site"}
                if {[llength $group]+[llength $unit] > $target} {
                    lappend result [list $key $group]; set group {}
                }
                set group [concat $group $unit]
            }
        }
        if {[llength $group]} {lappend result [list $key $group]}
    }
    # A third level must progress even if an artificial device has >target SLRs.
    if {[llength $result] >= [llength $frontier]} {
        set result {}
        for {set i 0} {$i < [llength $frontier]} {incr i $target} {
            lappend result [list UNKNOWN [lrange $frontier $i [expr {$i+$target-1}]]]
        }
    }
    return $result
}
proc f96::slr_pblock {slr_name} {
    set pb f96_$slr_name
    if {![llength [get_pblocks -quiet $pb]]} {
        create_pblock $pb
        set ranges {}
        foreach region [get_clock_regions -of_objects [get_slrs $slr_name]] {
            lappend ranges CLOCKREGION_${region}:CLOCKREGION_${region}
        }
        if {![llength $ranges]} {error "SLR has no clock regions: $slr_name"}
        resize_pblock [get_pblocks $pb] -add $ranges
        set_property IS_SOFT true [get_pblocks $pb]
    }
    return [get_pblocks $pb]
}
proc f96::scan {directory {physical 1}} {
    variable target
    file mkdir $directory
    phase "scan $directory"
    # Start from EVERY live net, including all generations of replicated logic.
    set candidates [get_nets -hier -filter "FLAT_PIN_COUNT > $target && TYPE != POWER && TYPE != GROUND"]
    set roots [get_nets -quiet -segments -top_net_of_hierarchical_group -of_objects [get_pins -quiet -of_objects $candidates]]
    set f [open $directory/high_fanout.tsv w]
    puts $f "net\tdriver\tref\tlogical\tphysical\tclock_loads\tstatus"
    set selected {}; array set seen {}; set total 0; set excluded 0; set unsupported 0
    foreach net $roots {
        set name [get_property NAME $net]
        if {[info exists seen($name)]} {continue}; set seen($name) 1
        # Do not expand a real global clock through every hierarchical segment.
        # This checks clock objects, not BUFG type, so BUFG controls remain eligible.
        set clocks_here [get_clocks -quiet -of_objects $net]
        if {[llength $clocks_here]} {
            puts $f "$name\t\tCLOCK_OBJECT\tNOT_ENUMERATED\tNOT_ENUMERATED\t[join $clocks_here ,]\tCLOCK_DISTRIBUTION"
            incr excluded; incr total; continue
        }
        if {[get_property FLAT_PIN_COUNT $net] > 10000} {phase "large_net_begin $name"}
        set segments [get_nets -quiet -segments $net]
        set sinks [lsort -unique [get_pins -quiet -of_objects $segments -filter {DIRECTION == IN && IS_LEAF == 1}]]
        if {[llength $sinks] <= $target} {continue}
        set drivers [get_pins -quiet -of_objects $segments -filter {DIRECTION == OUT && IS_LEAF == 1}]
        set input_ports [get_ports -quiet -of_objects $segments -filter {DIRECTION == IN}]
        set driver_count [expr {[llength $drivers]+[llength $input_ports]}]
        # Native Vivado collections cannot mix PIN and PORT object classes.
        if {![llength $drivers]} {set drivers $input_ports}
        set cells [get_cells -quiet -of_objects [get_pins -quiet -of_objects $segments -filter {DIRECTION == OUT && IS_LEAF == 1}]]
        set refs [values REF_NAME $cells]
        set clocks 0; foreach b [values IS_CLOCK $sinks] {if {$b} {incr clocks}}
        set phy -1
        # SITE_PIN has no IS_LEAF property; that predicate applies to PIN only.
        if {$physical} {set phy [llength [lsort -unique [values NAME [get_site_pins -quiet -of_objects $segments -filter {DIRECTION == IN}]]]]}
        set status SELECTED
        if {$refs in {VCC GND}} {set status CONSTANT}
        if {$clocks} {set status CLOCK_DISTRIBUTION}
        if {$status eq "SELECTED" && $driver_count != 1} {set status UNSUPPORTED_DRIVER_COUNT; incr unsupported}
        # A BUFG used only for control/data is deliberately NOT a clock exclusion.
        puts $f "$name\t[join $drivers ,]\t[join $refs ,]\t[llength $sinks]\t$phy\t$clocks\t$status"
        if {$status eq "SELECTED"} {
            lappend selected [dict create driver [lindex $drivers 0] driver_name [get_property NAME [lindex $drivers 0]] sinks $sinks ref $refs net $name]
        } else {incr excluded}
        incr total
        if {$total % 100 == 0} {phase "scan nets=$total selected=[llength $selected]"; flush $f}
    }
    close $f
    set f [open $directory/scan_summary.tsv w]
    puts $f "candidate_roots\thigh_fanout\tselected\texcluded\tunsupported_ordinary\tordinary_over_target\ttarget"
    puts $f "[array size seen]\t$total\t[llength $selected]\t$excluded\t$unsupported\t[expr {[llength $selected]+$unsupported}]\t$target"; close $f
    return $selected
}
proc f96::flatten_owned {directory} {
    file mkdir $directory
    set cells [get_cells -quiet hfg_identity_*]
    if {![llength $cells]} {return}
    set owned [dict create]; foreach c $cells init [values INIT $cells] {
        if {$init ne "2'h2"} {error "Old helper is not identity: $c"}
        dict set owned $c 1
    }
    set roots [dict create]
    foreach c $cells {
        set p [get_pins $c/I0]
        set dr [get_pins -quiet -of_objects [get_nets -quiet -segments -of_objects $p] -filter {DIRECTION == OUT && IS_LEAF == 1}]
        if {[llength $dr] != 1} {error "Old helper has ambiguous driver"}
        set dc [get_cells -of_objects $dr]
        if {![dict exists $owned $dc]} {dict set roots $dr 1}
    }
    set of [open $directory/flatten.tsv w]; puts $of "driver\tleaf_sinks\told_helpers\tcoverage"
    set oldnets [get_nets -quiet -segments -of_objects [get_pins -of_objects $cells -filter {DIRECTION == OUT && IS_LEAF == 1}]]
    set_property DONT_TOUCH false $cells
    set_property DONT_TOUCH false $oldnets
    dict for {driver unused} $roots {
        set pending [loads $driver]; set sinks {}; set visited [dict create]
        for {set index 0} {$index < [llength $pending]} {incr index} {
            set p [lindex $pending $index]
            set c [get_cells -of_objects $p]
            if {[dict exists $owned $c]} {
                if {[dict exists $visited $c]} {error "Old helper loop"}
                dict set visited $c 1
                lappend pending {*}[loads [get_pins $c/O]]
            } else {lappend sinks $p}
        }
        disconnect $sinks
        connect_net -hierarchical -net [get_nets -of_objects $driver] -objects $sinks
        remove_cell [get_cells [dict keys $visited]]
        if {[loads $driver] ne [lsort $sinks]} {error "Flattened sink set mismatch"}
        puts $of "$driver\t[llength $sinks]\t[dict size $visited]\tEXACT_PASS"; flush $of
    }
    close $of
    if {[llength [get_cells -quiet hfg_identity_*]]} {error "Unreached old helpers"}
}
proc f96::apply {selected directory} {
    variable target; variable serial; variable created; variable max_new_luts
    variable cr; variable slr
    file mkdir $directory
    set f [open $directory/application.tsv w]
    puts $f "driver\tref\tbefore\tafter\tnew_luts\tlevels\tcoverage"
    set bf [open $directory/branches.tsv w]
    puts $bf "cell\troot\tlevel\thint\tloads"
    set original [open $directory/original_sinks.tcllist.tsv w]
    puts $original "driver\tsinks_tcl_list"
    set ef [open $directory/new_edges.tcllist.tsv w]
    puts $ef "helper\tsinks_tcl_list"
    set count 0
    foreach item $selected {
        set driver [dict get $item driver]; set before [dict get $item sinks]
        if {[loads $driver] ne $before} {error "Stale discovery: $driver"}
        puts $original "$driver\t[list $before]"; flush $original
        set root [get_nets -of_objects $driver]
        # A later cleanup may extend an owned tree. Unlock only its own helper
        # inputs and root segments during this verified local rewrite.
        set owned_inputs {}
        foreach p [values NAME $before] {
            if {[regexp {^(f96_identity_[0-9]+)/I0$} $p unused owner]} {lappend owned_inputs $owner}
        }
        if {[llength $owned_inputs]} {
            set_property DONT_TOUCH false [get_nets -segments -of_objects $driver]
            set_property DONT_TOUCH false [get_cells $owned_inputs]
        }
        set frontier $before; set edges [dict create]; set level 0; set start $created
        while {[llength $frontier] > $target} {
            set next {}
            foreach entry [groups $frontier $level] {
                lassign $entry hint group
                set name f96_identity_[incr serial]
                if {[llength [get_cells -quiet $name]]} {error "Helper collision: $name"}
                if {$created >= $max_new_luts} {error "Identity LUT budget exhausted"}
                create_cell -reference LUT1 $name
                set_property INIT 2'h2 [get_cells $name]
                set_property DONT_TOUCH true [get_cells $name]
                create_net ${name}_out
                connect_net -hierarchical -net $root -objects [get_pins $name/I0]
                connect_net -net [get_nets ${name}_out] -objects [get_pins $name/O]
                disconnect $group
                connect_net -hierarchical -net [get_nets ${name}_out] -objects $group
                if {[loads [get_pins $name/O]] ne [lsort $group]} {error "Branch connectivity mismatch"}
                set_property DONT_TOUCH true [get_nets -segments -of_objects [get_pins $name/O]]
                # One soft CR rectangle per first-level helper; upper levels use SLR.
                if {[regexp {^(SLR[0-9]+)/(.+)$} $hint unused sr region]} {
                    set cr($name) $region; set slr($name) $sr
                    set pb f96_$region
                    if {![llength [get_pblocks -quiet $pb]]} {
                        create_pblock $pb; resize_pblock [get_pblocks $pb] -add CLOCKREGION_${region}:CLOCKREGION_${region}
                        set_property IS_SOFT true [get_pblocks $pb]
                    }
                    add_cells_to_pblock [get_pblocks $pb] [get_cells $name]
                } elseif {[regexp {^SLR[0-9]+$} $hint]} {
                    set slr($name) $hint
                    add_cells_to_pblock [slr_pblock $hint] [get_cells $name]
                }
                dict set edges [get_pins $name/I0] $group
                lappend next [get_pins $name/I0]; incr created
                puts $bf "$name\t$driver\t$level\t$hint\t[llength $group]"
                puts $ef "$name\t[list $group]"
            }
            set frontier $next; incr level
        }
        if {[loads $driver] ne [lsort $frontier]} {error "Root connectivity mismatch"}
        # Preserve the repaired root as well as every helper output. Otherwise
        # equivalent-driver rewiring can attach new sinks during later placement.
        set_property DONT_TOUCH true [get_nets -segments -of_objects $driver]
        if {[llength $owned_inputs]} {set_property DONT_TOUCH true [get_cells $owned_inputs]}
        # Traverse names by complete levels. Repeated lindex/lrange on Vivado's
        # native PIN containers can materialize the entire container each time.
        set pending [values NAME $frontier]; set recovered {}
        while {[llength $pending]} {
            set next {}
            foreach p $pending {
                if {[dict exists $edges $p]} {
                    foreach child [values NAME [dict get $edges $p]] {lappend next $child}
                } else {lappend recovered $p}
            }
            set pending $next
        }
        if {[lsort $recovered] ne [lsort [values NAME $before]]} {error "Original sink coverage mismatch"}
        puts $f "$driver\t[dict get $item ref]\t[llength $before]\t[llength $frontier]\t[expr {$created-$start}]\t$level\tEXACT_PASS"
        flush $f; flush $bf
        incr count
        if {$count % 25 == 0} {phase "applied=$count/[llength $selected] helpers=$created"}
    }
    close $f; close $bf; close $original; close $ef
    return $created
}
