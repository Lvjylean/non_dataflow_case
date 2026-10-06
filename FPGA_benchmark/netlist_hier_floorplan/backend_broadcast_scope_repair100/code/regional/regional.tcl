source [file join [file dirname [info script]] mobility.tcl]
source [file join [file dirname [info script]] regional_policy.tcl]
namespace eval rf {
    variable positions; array set positions {}
    variable site_regions; array set site_regions {}
    variable region_slrs; array set region_slrs {}
    variable saved_cells; array set saved_cells {}
    variable saved_nets; array set saved_nets {}
    variable ancestor_cache; array set ancestor_cache {}
    variable asynchronous; array set asynchronous {}
}
proc rf::log {message} {puts "REGIONAL [clock milliseconds] $message"; flush stdout}
proc rf::reset {} {
    foreach name {positions site_regions region_slrs saved_cells saved_nets ancestor_cache asynchronous} {
        variable $name
        array unset $name *
    }
    # Native object and connectivity caches never survive an edit or reopen.
    foreach name {pin_objects cell_objects positions refs site_slrs} {array unset ::sb::$name *}
    set ::sb::signal_cache {}
}
proc rf::position {cell} {
    variable positions; variable site_regions; variable region_slrs
    if {[info exists positions($cell)]} {return $positions($cell)}
    set object [sb::cell $cell]
    set loc [get_property LOC $object]
    if {$loc eq ""} {return {}}
    if {![info exists site_regions($loc)]} {
        set crs [sb::names [get_clock_regions -of_objects [get_sites [list $loc]]]]
        require [expr {[llength $crs] == 1}] "Ambiguous region for $cell"
        set site_regions($loc) [lindex $crs 0]
    }
    set cr $site_regions($loc)
    if {![info exists region_slrs($cr)]} {
        set slrs [sb::names [get_slrs -of_objects [get_clock_regions [list $cr]]]]
        require [expr {[llength $slrs] == 1}] "Ambiguous SLR for $cr"
        set region_slrs($cr) [lindex $slrs 0]
    }
    set positions($cell) [dict create loc $loc bel [get_property BEL $object] cr $cr slr $region_slrs($cr)]
    return $positions($cell)
}
proc rf::preload {names} {
    variable positions
    # Unique receiving cells only; never prefetch all design LOC/BEL properties.
    foreach c [lsort -unique $names] {if {![info exists positions($c)]} {position $c}}
}
proc rf::legacy_exclusions {plan} {
    # Exclude every driver whose exact connectivity is certified by the old ECO.
    array set pins {}
    dict for {c item} [dict get $plan data] {
        set pins($c/Q) 1
        dict for {p value} [dict get $item inputs] {
            set signal [dict get $value signal]
            if {[lindex $signal 0] eq "drivers"} {foreach driver [lindex $signal 1] {set pins($driver) 1}}
        }
        dict for {c value} [dict get $item helpers] {set pins($c/O) 1}
    }
    dict for {name item} [dict get $plan ce] {
        set pins([dict get $item driver]) 1
        dict for {p value} [dict get $item inputs] {
            set signal [dict get $value signal]
            if {[lindex $signal 0] eq "drivers"} {foreach driver [lindex $signal 1] {set pins($driver) 1}}
        }
        foreach pin [dict get $item loads] {
            set c [file dirname $pin]
            if {[string match sbeco_* $c]} {continue}
            set pins($c/Q) 1
            dict for {p value} [sb::inputs $c] {
                set signal [dict get $value signal]
                if {[lindex $signal 0] eq "drivers"} {foreach driver [lindex $signal 1] {set pins($driver) 1}}
            }
        }
    }
    return [array names pins]
}
proc rf::protected_ancestor {cell} {
    variable ancestor_cache
    if {[info exists ancestor_cache($cell)]} {return $ancestor_cache($cell)}
    set parent [file dirname $cell]
    set result ""
    if {$parent ni {. / {}}} {
        if {[sb::one_bit [get_property DONT_TOUCH [sb::cell $parent]]]} {set result $parent} \
        else {set result [protected_ancestor $parent]}
    }
    set ancestor_cache($cell) $result
    return $result
}
proc rf::asynchronous {cell} {
    variable asynchronous
    if {![info exists asynchronous($cell)]} {set asynchronous($cell) [sb::one_bit [get_property ASYNC_REG [sb::cell $cell]]]}
    return $asynchronous($cell)
}
proc rf::discover {out excluded {explicit_drivers {}}} {
    variable config; variable serial
    reset
    set serial 0
    require [expr {![llength [get_cells -quiet rfd_lut_*]]}] "Regional ECO already exists; use its saved plan to resume"
    array set blocked {}; foreach driver $excluded {set blocked($driver) 1}
    set f [open $out/regional_candidates.tsv w]
    puts $f "net\tdriver\tref\tlogical_fanout\tsectors\tadded_luts\tstatus\tquery_ms"
    set start [clock milliseconds]; set roots {}; set added 0; set visited 0
    array set fixed {}; array set seen {}
    if {[llength $explicit_drivers]} {
        set objects [get_nets -quiet -segments -top_net_of_hierarchical_group -of_objects [get_pins $explicit_drivers]]
    } else {
        # One native filtered query. Hierarchical segment count is never fanout.
        set candidates [get_nets -hier -filter "FLAT_PIN_COUNT > [dict get $config min_fanout] && TYPE != POWER && TYPE != GROUND"]
        set objects [get_nets -quiet -segments -top_net_of_hierarchical_group $candidates]
    }
    set root_names [lsort -unique [sb::names $objects]]
    unset objects
    log "discovery_candidates=[llength $root_names]"
    foreach name $root_names {
        set tick [clock milliseconds]; incr visited
        if {[info exists seen($name)]} {continue}; set seen($name) 1
        set n [get_nets -quiet [list $name]]
        set status ""; set driver ""; set ref ""; set fanout 0; set sectors 0; set count 0
        if {[llength [get_clocks -quiet -of_objects $n]] || [get_property TYPE $n] in {POWER GROUND}} {
            set status clock_or_constant
        } else {
            set segments [get_nets -quiet -segments $n]
            set drivers [sb::names [get_pins -quiet -of_objects $segments -filter {DIRECTION == OUT && IS_LEAF == 1}]]
            if {[llength $drivers] != 1 || [llength [get_ports -quiet -of_objects $segments]]} {set status unsupported_driver_or_port} else {
                set driver [lindex $drivers 0]; set cell [file dirname $driver]; set ref [sb::ref $cell]
                if {[info exists blocked($driver)]} {set status preserved_legacy_eco} \
                elseif {[known_protected_ip $driver]} {set status protected_ip_driver} \
                elseif {![allowed_driver $ref [file tail $driver]]} {set status unsupported_driver} \
                elseif {[protected_ancestor $cell] ne ""} {set status protected_hierarchy} \
                elseif {[asynchronous $cell]} {set status asynchronous_register} \
                elseif {[sb::one_bit [get_property IS_ROUTE_FIXED $n]] || [has_fixed_route [get_property FIXED_ROUTE $n]]} {set status fixed_route}
                if {$status eq ""} {
                    set pins [get_pins -quiet -of_objects $segments -filter {DIRECTION == IN && IS_LEAF == 1}]
                    set sinks [lsort -unique [sb::names $pins]]; set fanout [llength $sinks]
                    if {$fanout < [dict get $config min_fanout]} {set status below_minimum}
                    foreach value [sb::values IS_CLOCK $pins] {if {[sb::one_bit $value]} {set status clock_sink; break}}
                    unset pins
                    if {$status eq ""} {
                        set cells [list $cell]
                        foreach p $sinks {
                            set c [file dirname $p]
                            if {[known_protected_ip $p]} {set status protected_ip_sink; break}
                            if {![allowed_sink [sb::ref $c] [file tail $p]]} {set status unsupported_sink; break}
                            if {[asynchronous $c]} {set status asynchronous_register; break}
                            if {[protected_ancestor $c] ne ""} {set status protected_hierarchy; break}
                            lappend cells $c
                        }
                    }
                    if {$status eq ""} {
                        preload $cells
                        set source [position $cell]; set rows {}
                        if {$source eq ""} {set status unplaced_source}
                        foreach p $sinks {
                            set pos [position [file dirname $p]]
                            if {$pos eq ""} {set status unplaced_sink; break}
                            lappend rows [list $p $pos]
                        }
                        if {$status eq ""} {
                            set root [plan_root $driver $source $rows]
                            set status [dict get $root status]
                            if {$status eq "selected"} {
                                set count [llength [dict get $root nodes]]; incr added $count
                                require [expr {$added <= [dict get $config max_luts]}] "Regional LUT budget exhausted before editing"
                                set sectors [llength [dict get $root frontier]]
                                dict set root net $name
                                dict set root ref $ref
                                lappend roots $root
                                foreach c [lsort -unique $cells] {set fixed($c) [position $c]}
                            }
                        }
                    }
                }
            }
        }
        puts $f "$name\t$driver\t$ref\t$fanout\t$sectors\t$count\t$status\t[expr {[clock milliseconds]-$tick}]"
        if {$visited % 32 == 0} {log "visited=$visited selected=[llength $roots] added_luts=$added"; flush $f}
    }
    close $f
    # Export each large dictionary once, after array-based hot loops finish.
    set plan [dict create schema regional-fanout-v1 config $config roots $roots lut_added $added fixed {} positions_before [array get fixed] placement_policy shallow-destination-v1 discovery_ms [expr {[clock milliseconds]-$start}]]
    log "discovery_complete selected=[llength $roots] added_luts=$added milliseconds=[dict get $plan discovery_ms]"
    return $plan
}
proc rf::property_batches {property value names kind} {
    foreach batch [sb::chunks $names 256] {
        if {$kind eq "cell"} {set objects [get_cells $batch]} else {set objects [get_nets $batch]}
        require [expr {[llength $objects] == [llength $batch]}] "Missing $kind in property batch"
        if {$value eq ""} {reset_property $property $objects} else {set_property $property $value $objects}
    }
}
proc rf::unlock_cells {names} {
    variable saved_cells
    foreach name [lsort -unique $names] {
        while {$name ni {. / {}}} {
            if {![info exists saved_cells($name)]} {
                set value [get_property DONT_TOUCH [sb::cell $name]]
                set saved_cells($name) $value
                if {[sb::one_bit $value]} {set_property DONT_TOUCH false [sb::cell $name]}
            }
            set name [file dirname $name]
        }
    }
}
proc rf::unlock_nets {objects} {
    variable saved_nets
    set change {}
    foreach name [sb::values NAME $objects] value [sb::values DONT_TOUCH $objects] {
        if {![info exists saved_nets($name)]} {
            set saved_nets($name) $value
            if {[sb::one_bit $value]} {lappend change $name}
        }
    }
    property_batches DONT_TOUCH false $change net
}
proc rf::restore {} {
    foreach kind {cell net} {
        if {$kind eq "cell"} {variable saved_cells; array set saved [array get saved_cells]} \
        else {variable saved_nets; array set saved [array get saved_nets]}
        array set groups {}
        foreach name [array names saved] {lappend groups($saved($name)) $name}
        foreach value [array names groups] {property_batches DONT_TOUCH $value $groups($value) $kind}
        array unset saved *; array unset groups *
    }
}
proc rf::connect_pairs {net pins} {
    if {$::execopt::enabled} {execopt::queue_connections $net $pins; return}
    foreach batch [sb::chunks $pins 256] {
        set pairs {}; set object [get_nets [list $net]]
        foreach p [get_pins [split [join $batch \n] \n]] {lappend pairs $object $p}
        connect_net -hierarchical -dict $pairs
    }
}
proc rf::bind {node} {
    if {$::execopt::enabled} {execopt::queue_region $node; return}
    set name [dict get $node name]
    set regions [dict get $node regions]
    set pb rfd_region_[join $regions _]
    if {![llength [get_pblocks -quiet $pb]]} {
        create_pblock $pb
        set ranges {}; foreach cr $regions {lappend ranges CLOCKREGION_${cr}:CLOCKREGION_${cr}}
        resize_pblock [get_pblocks $pb] -add $ranges
        set_property EXCLUDE_PLACEMENT false [get_pblocks $pb]
        # Vivado 2023.2 resets IS_SOFT when EXCLUDE_PLACEMENT is written.
        set_property IS_SOFT false [get_pblocks $pb]
    }
    add_cells_to_pblock [get_pblocks $pb] [get_cells [list $name]]
}
proc rf::region_constraints {plan out {repair 0}} {
    # At most one query per region, never one whole-netlist query per LUT.
    array set members {}; array set ranges {}
    foreach root [dict get $plan roots] {
        foreach node [dict get $root nodes] {
            set pb rfd_region_[join [dict get $node regions] _]
            lappend members($pb) [dict get $node name]
            if {![info exists ranges($pb)]} {
                set ranges($pb) {}
                foreach cr [dict get $node regions] {lappend ranges($pb) CLOCKREGION_${cr}:CLOCKREGION_${cr}}
            }
        }
    }
    file mkdir $out
    set f [open $out/regional_constraints.tsv w]
    puts $f "pblock\tsoft\texclude_placement\tranges\tmembers\trepaired"
    foreach name [lsort [array names members]] {
        set pb [get_pblocks -quiet [list $name]]
        require [expr {[llength $pb] == 1}] "Missing regional Pblock: $name"
        set actual [lsort [sb::names [get_cells -quiet -of_objects $pb]]]
        require [expr {$actual eq [lsort $members($name)]}] "Regional Pblock membership mismatch: $name"
        set grid [lsort [get_property GRID_RANGES $pb]]
        require [expr {[geo::expand_ranges $grid] eq [geo::expand_ranges $ranges($name)]}] "Regional Pblock range mismatch: $name actual={$grid} expected={$ranges($name)}"
        if {$repair} {
            set_property EXCLUDE_PLACEMENT false $pb
            set_property IS_SOFT false $pb
        }
        set soft [get_property IS_SOFT $pb]
        set exclude [get_property EXCLUDE_PLACEMENT $pb]
        puts $f "$name\t$soft\t$exclude\t$grid\t[llength $actual]\t$repair"
        flush $f
        require [expr {![sb::one_bit $soft] && ![sb::one_bit $exclude]}] "Regional Pblock must be hard and nonexclusive: $name soft=$soft exclude=$exclude"
    }
    close $f
}
proc rf::apply {plan out} {
    variable saved_cells; variable saved_nets
    validate_edit_scope $plan
    execopt::clear_queues
    reset
    configure [dict get $plan config]
    file mkdir $out
    set f [open $out/regional_runtime.tsv w]
    puts $f "driver\tsinks\tnew_luts\tvalidate_ms\tunlock_unroute_ms\tcreate_ms\tdisconnect_ms\tconnect_bind_ms\tverify_ms\ttotal_ms"
    # Verify every old location once, before changing any net.
    set positions_before [dict get $plan fixed]
    if {[dict exists $plan positions_before]} {set positions_before [dict get $plan positions_before]}
    dict for {name expected} $positions_before {
        require [expr {[position $name] eq $expected}] "Stale regional position: $name"
    }
    set code [catch {
        foreach root [dict get $plan roots] {
            set tick [clock milliseconds]
            set driver [dict get $root driver]; set before [dict get $root sinks]
            require [expr {[sb::loads $driver] eq $before}] "Stale regional sink set: $driver"
            require [expr {[sb::ref [file dirname $driver]] eq [dict get $root ref]}] "Stale regional driver type"
            validate_tree $root
            set validated [clock milliseconds]
            set segments [get_nets -segments -of_objects [sb::pin $driver]]
            set segment_names [sb::names $segments]
            set mapping {}; set covered {}
            foreach net $segment_names {
                set pins [sb::names [get_pins -quiet -of_objects [get_nets [list $net]] -filter {DIRECTION == IN && IS_LEAF == 1}]]
                if {[llength $pins]} {lappend mapping [list $net $pins]; lappend covered {*}$pins}
            }
            require [expr {[lsort $covered] eq $before}] "Regional segment mapping mismatch"
            set cells [list [file dirname $driver]]; foreach p $before {lappend cells [file dirname $p]}
            unlock_cells $cells
            unlock_nets $segments
            route_design -unroute -nets $segments
            unset segments
            set unlocked [clock milliseconds]
            set names {}; set nets {}
            foreach node [dict get $root nodes] {
                set name [dict get $node name]
                require [expr {![llength [get_cells -quiet [list $name]]] && ![llength [get_nets -quiet [list ${name}_out]]]}] "Distribution LUT/net collision"
                lappend names $name; lappend nets ${name}_out
            }
            foreach batch [sb::chunks $names 128] {create_cell -reference LUT1 $batch}
            foreach batch [sb::chunks $nets 128] {create_net $batch}
            property_batches INIT 2'h2 $names cell
            property_batches IS_LOC_FIXED false $names cell
            property_batches IS_BEL_FIXED false $names cell
            set built [clock milliseconds]
            foreach pair $mapping {
                lassign $pair net pins
                if {$::execopt::enabled} {execopt::disconnect_segment $net $pins} else {
                    foreach batch [sb::chunks $pins 256] {disconnect_net -net [get_nets [list $net]] -pinlist [get_pins $batch]}
                }
            }
            set disconnected [clock milliseconds]
            foreach node [dict get $root nodes] {
                set name [dict get $node name]
                connect_pairs ${name}_out [linsert [dict get $node loads] 0 $name/O]
                bind $node
            }
            set root_net [get_property NAME [get_nets -of_objects [sb::pin $driver]]]
            connect_pairs $root_net [dict get $root frontier]
            execopt::flush_connections
            property_batches DONT_TOUCH true $names cell
            foreach batch [sb::chunks $names 128] {
                set ns [get_nets -segments -of_objects [get_pins -of_objects [get_cells $batch] -filter {DIRECTION == OUT}]]
                property_batches DONT_TOUCH true [lsort -unique [sb::names $ns]] net
            }
            set connected [clock milliseconds]
            verify_root $root 0
            set finished [clock milliseconds]
            puts $f "$driver\t[llength $before]\t[llength $names]\t[expr {$validated-$tick}]\t[expr {$unlocked-$validated}]\t[expr {$built-$unlocked}]\t[expr {$disconnected-$built}]\t[expr {$connected-$disconnected}]\t[expr {$finished-$connected}]\t[expr {$finished-$tick}]"
            flush $f
            log "applied driver=$driver root_fanout=[llength [dict get $root frontier]] added_luts=[llength $names] milliseconds=[expr {$finished-$tick}]"
        }
        execopt::flush_regions
    } message options]
    execopt::clear_queues
    # Restore original protection even on failure; the failed in-memory design is discarded.
    set restore_code [catch {restore} restore_message]
    close $f
    if {$code} {return -options $options $message}
    require [expr {!$restore_code}] "Protection restoration failed: $restore_message"
    set fixed [dict keys [dict get $plan fixed]]
    property_batches IS_LOC_FIXED true $fixed cell
    property_batches IS_BEL_FIXED true $fixed cell
    dict set plan protection [dict create cells [array get saved_cells] nets [array get saved_nets]]
    return $plan
}
proc rf::verify_root {root placed} {
    require [expr {[sb::loads [dict get $root driver]] eq [lsort [dict get $root frontier]]}] "Regional source connectivity mismatch"
    foreach node [dict get $root nodes] {
        set name [dict get $node name]
        require [expr {[sb::ref $name] eq "LUT1" && [string tolower [get_property INIT [sb::cell $name]]] eq "2'h2"}] "Distribution truth table changed: $name"
        require [expr {[sb::loads $name/O] eq [lsort [dict get $node loads]]}] "Distribution branch mismatch: $name"
        require [sb::one_bit [get_property DONT_TOUCH [sb::cell $name]]] "Distribution protection lost: $name"
        if {[dict exists $node movable] && [dict get $node movable]} {
            require [expr {![sb::one_bit [get_property IS_LOC_FIXED [sb::cell $name]]] && ![sb::one_bit [get_property IS_BEL_FIXED [sb::cell $name]]]}] "Distribution LUT acquired an exact location lock: $name"
        }
        if {$placed} {
            set pos [position $name]
            require [expr {$pos ne "" && [dict get $pos cr] in [dict get $node regions]}] "Distribution LUT outside its physical region: $name actual={$pos} expected={[dict get $node regions]}"
        }
    }
    validate_tree $root
}
proc rf::restore_native_lut_protection {plan out} {
    # Vivado placement can promote an originally unset DONT_TOUCH on a fixed
    # original LUT1. Restore only this measured transition, never lost protection.
    # Stage-boundary batches avoid per-connection queries of the saved plan.
    if {![dict exists $plan protection]} {return 0}
    reset
    array set fixed [dict get $plan fixed]
    file mkdir $out
    set f [open $out/native_protection_deltas.tsv w]
    puts $f "kind\tname\texpected\tactual\taction"
    set pending {}; set rejected 0
    foreach kind {cells nets} {
        set records [dict get $plan protection $kind]
        array set expected $records
        foreach batch [sb::chunks [dict keys $records] 256] {
            if {$kind eq "cells"} {set objects [get_cells -quiet $batch]} else {set objects [get_nets -quiet $batch]}
            require [expr {[llength $objects] == [llength $batch]}] "Original protected object missing before native restoration"
            foreach name [sb::values NAME $objects] value [sb::values DONT_TOUCH $objects] {
                require [info exists expected($name)] "Unexpected native property object: $name"
                if {$value eq $expected($name)} {continue}
                set allowed 0
                if {$kind eq "cells" && $expected($name) eq "" && [sb::one_bit $value] && [info exists fixed($name)]} {
                    set object [sb::cell $name]
                    set allowed [expr {[get_property REF_NAME $object] eq "LUT1" &&
                        [sb::one_bit [get_property IS_LOC_FIXED $object]] &&
                        [sb::one_bit [get_property IS_BEL_FIXED $object]] &&
                        [position $name] eq $fixed($name)}]
                }
                if {$allowed} {
                    lappend pending $name
                    puts $f "$kind\t$name\t$expected($name)\t$value\trestore_original_unset"
                } else {
                    incr rejected
                    puts $f "$kind\t$name\t$expected($name)\t$value\trejected_unobserved_transition"
                }
            }
        }
        array unset expected *
    }
    close $f
    # Validate the complete delta set before changing any original property.
    require [expr {!$rejected}] "Unrecognized protection drift; no properties restored (see $out/native_protection_deltas.tsv)"
    property_batches DONT_TOUCH {} $pending cell
    set sticky {}
    foreach batch [sb::chunks $pending 256] {
        set objects [get_cells $batch]
        require [expr {[llength $objects] == [llength $batch]}] "Original cell missing after native restoration"
        foreach name [sb::values NAME $objects] value [sb::values DONT_TOUCH $objects] {
            if {$value eq ""} {continue}
            require [sb::one_bit $value] "Unexpected protection value after native restoration: $name"
            lappend sticky $name
        }
    }
    if {[llength $sticky]} {
        set f [open $out/native_protection_sticky.txt w]
        foreach name $sticky {puts $f $name}
        close $f
        return -code error -errorcode {RF NATIVE_LUT_PROTECTION_STICKY} \
            "Native LUT protection remained set on [llength $sticky] fixed original LUT1 cells; independent checkpoint reopening is required"
    }
    set f [open $out/native_protection_restore.txt w]
    puts $f "Restored original unset DONT_TOUCH on [llength $pending] fixed original LUT1 cells; full structural/property validation remains mandatory."
    close $f
    return [llength $pending]
}
proc rf::verify {plan out placed} {
    reset
    configure [dict get $plan config]
    file mkdir $out
    region_constraints $plan $out
    set f [open $out/regional_structure.tsv w]
    puts $f "driver\toriginal_fanout\troot_fanout\tnew_luts\tcoverage\tplaced"
    foreach root [dict get $plan roots] {
        verify_root $root $placed
        puts $f "[dict get $root driver]\t[llength [dict get $root sinks]]\t[llength [dict get $root frontier]]\t[llength [dict get $root nodes]]\tEXACT_PASS\t$placed"
    }
    close $f
    dict for {name expected} [dict get $plan fixed] {
        require [expr {[position $name] eq $expected}] "Regional source/receiver moved: $name"
    }
    if {[dict exists $plan protection]} {
        foreach kind {cells nets} {
            set records [dict get $plan protection $kind]
            array set expected_properties $records
            foreach batch [sb::chunks [dict keys $records] 256] {
                if {$kind eq "cells"} {set objects [get_cells $batch]} else {set objects [get_nets $batch]}
                require [expr {[llength $objects] == [llength $batch]}] "Original protected object missing"
                foreach name [sb::values NAME $objects] value [sb::values DONT_TOUCH $objects] {
                    require [expr {$value eq $expected_properties($name)}] "Original DONT_TOUCH not restored: $name"
                }
            }
            array unset expected_properties *
        }
    }
    set observed [llength [get_cells -quiet rfd_lut_*]]
    require [expr {$observed == [dict get $plan lut_added]}] "Regional LUT count changed"
}
proc rf::reports {plan out} {
    file mkdir $out
    set f [open $out/regional_positions.tsv w]
    puts $f "cell\tkind\tloc\tcr\tslr\ttarget_regions\tdestination_sector\tfanout"
    reset
    foreach root [dict get $plan roots] {
        foreach node [dict get $root nodes] {
            set name [dict get $node name]; set pos [position $name]
            if {$pos eq ""} {continue}
            set sector ""; if {[dict exists $node destination_sector]} {set sector [dict get $node destination_sector]}
            puts $f "$name\t[dict get $node kind]\t[dict get $pos loc]\t[dict get $pos cr]\t[dict get $pos slr]\t[join [dict get $node regions] ,]\t$sector\t[llength [dict get $node loads]]"
        }
    }
    close $f
}
