# Pure graph planner. A replica represents the same function/state as its origin.
namespace eval lb {}
proc lb::output_pin {ref} {
    if {$ref in {FDRE FDSE}} {return Q}
    if {[regexp {^LUT[1-6]$} $ref]} {return O}
    return ""
}
proc lb::ordinary_input {ref pin} {
    if {$ref in {FDRE FDSE}} {return [expr {$pin in {D CE R S}}]}
    if {[regexp {^LUT[1-6]$} $ref]} {return [regexp {^I[0-5]$} $pin]}
    if {$ref in {MUXF7 MUXF8 MUXF9}} {return [expr {$pin in {I0 I1 S}}]}
    if {[regexp {^RAMB(18|36)E[12]$} $ref]} {
        return [regexp {^(DI|DIN|DIP|ADDR|ENARDEN|ENBWREN|WEA|WEBWE|REGCE)} $pin]
    }
    if {[regexp {^URAM288(_BASE)?$} $ref]} {
        return [regexp {^(DIN_[AB]|ADDR_[AB]|EN_[AB]|BWE_[AB]|RDB_WR_[AB])($|\[)} $pin]
    }
    return 0
}
proc lb::input_source {ref pin} {
    if {[output_pin $ref] eq $pin} {return 1}
    if {$ref in {MUXF7 MUXF8 MUXF9} && $pin eq "O"} {return 1}
    return [expr {[sb::data_input_kind $ref $pin] in {bram_data uram_data}}]
}
proc lb::resolve {snapshot copies key slr} {
    if {[dict exists $copies $key $slr]} {
        return "[dict get $copies $key $slr]/[dict get $snapshot roots $key pin]"
    }
    return $key
}
proc lb::graph {snapshot copies} {
    set expected {}; set moves {}; set new_inputs {}; set owners {}; set replicas {}
    dict for {key net} [dict get $snapshot nets] {
        if {[dict get $net kind] eq "ordinary"} {dict set expected $key {}}
    }
    dict for {key byslr} $copies {
        set root [dict get $snapshot roots $key]
        dict for {slr name} $byslr {
            dict set replicas $name [dict create key $key slr $slr]
            dict set expected "$name/[dict get $root pin]" {}
        }
    }
    # Plan every original receiving pin exactly once, including adjacent candidates.
    dict for {key net} [dict get $snapshot nets] {
        if {[dict get $net kind] ne "ordinary"} {continue}
        foreach sink [dict get $net before] {
            set target $key
            if {[dict exists $copies $key]} {
                set target [resolve $snapshot $copies $key [dict get $snapshot pin_slrs $sink]]
            }
            dict lappend expected $target $sink
            if {$target ne $key} {dict set moves $sink [list $key $target]}
        }
    }
    dict for {name item} $replicas {
        set root [dict get $snapshot roots [dict get $item key]]
        dict for {pin sig} [dict get $root inputs] {
            set key [dict get $sig key]
            set target [resolve $snapshot $copies $key [dict get $item slr]]
            set sink "$name/$pin"
            dict set new_inputs $sink $target
            dict set owners $sink [list [dict get $item key] [dict get $item slr]]
            if {[dict get $sig kind] eq "ordinary"} {dict lappend expected $target $sink}
        }
    }
    dict for {key sinks} $expected {
        sb::require [expr {[llength $sinks] == [llength [lsort -unique $sinks]]}] "Duplicate planned sink: $key"
        dict set expected $key [lsort $sinks]
    }
    return [dict create expected $expected moves $moves new_inputs $new_inputs owners $owners replicas $replicas]
}
proc lb::select {snapshot {min_fanout 16} {max_copies 8192}} {
    set copies {}; set decisions {}; set serial 0
    dict for {key root} [dict get $snapshot roots] {
        set groups {}
        foreach sink [dict get $snapshot nets $key before] {
            dict lappend groups [dict get $snapshot pin_slrs $sink] $sink
        }
        if {[llength [dict get $snapshot nets $key before]] < $min_fanout} {
            dict set decisions $key below_minimum; continue
        }
        if {[dict size $groups] < 2} {dict set decisions $key single_sink_SLR; continue}
        set accepted 0
        foreach slr [lsort [dict keys $groups]] {
            if {$slr eq [dict get $root slr]} {continue}
            set cost 0; set seen {}
            dict for {pin sig} [dict get $root inputs] {
                if {[dict get $sig kind] ne "ordinary"} {continue}
                set inputkey [dict get $sig key]
                if {[dict exists $seen $inputkey]} {continue}; dict set seen $inputkey 1
                set source [dict get $sig slr]
                if {$source eq ""} {incr cost 3} else {incr cost [sb::boundary $source $slr]}
            }
            set benefit [expr {[llength [dict get $groups $slr]] * [sb::boundary [dict get $root slr] $slr]}]
            if {$benefit <= $cost} {dict set decisions "$key@$slr" nonpositive_boundary_gain; continue}
            if {$serial >= $max_copies} {dict set decisions "$key@$slr" replica_budget; continue}
            incr serial; incr accepted
            set kind [expr {[dict get $root ref] in {FDRE FDSE} ? "ff" : "lut"}]
            dict set copies $key $slr [format sbeco_local_%s_%05d_%s $kind $serial $slr]
        }
        dict set decisions $key [expr {$accepted ? "selected" : "no_profitable_target"}]
    }
    # Shared upstream nets are budgeted globally, after all functional rewiring.
    set iterations 0
    while {1} {
        incr iterations
        set graph [graph $snapshot $copies]; set reject {}
        dict for {key sinks} [dict get $graph expected] {
            set limit 99
            if {[dict exists $snapshot nets $key]} {
                set limit [expr {max(99,[llength [dict get $snapshot nets $key before]])}]
            }
            set excess [expr {[llength $sinks]-$limit}]
            if {$excess <= 0} {continue}
            # A target SLR group can itself exceed the cap. Reject that replica;
            # the ordinary regional tree stage retains responsibility for the net.
            set cell [file dirname $key]
            if {[dict exists $graph replicas $cell]} {
                set replica [dict get $graph replicas $cell]
                dict set reject [list [dict get $replica key] [dict get $replica slr]] 1
                continue
            }
            foreach sink [lsort -decreasing $sinks] {
                if {![dict exists $graph owners $sink]} {continue}
                set owner [dict get $graph owners $sink]
                dict set reject $owner 1
                if {[incr excess -1] <= 0} {break}
            }
            sb::require [expr {$excess<=0}] "Existing output cannot meet copy cap: $key"
        }
        if {![dict size $reject]} {break}
        dict for {owner unused} $reject {
            lassign $owner key slr
            dict unset copies $key $slr
            if {![dict size [dict get $copies $key]]} {dict unset copies $key}
            dict set decisions "$key@$slr" projected_upstream_fanout
        }
        sb::require [expr {$iterations <= $serial+1}] "Fanout admission failed to converge"
    }
    dict for {key root} [dict get $snapshot roots] {
        if {[dict get $decisions $key] eq "selected" && ![dict exists $copies $key]} {
            dict set decisions $key rejected_by_global_fanout_budget
        }
    }
    return [dict create schema slr-local-functional-v1 snapshot $snapshot copies $copies graph $graph decisions $decisions]
}

proc lb::edit_scope {local} {
    # Keep exact certificates for edited outputs and their shared input nets.
    # Rejected/unrelated candidates must remain available to the regional stage.
    set all [dict get $local snapshot]; set copies [dict get $local copies]
    set snapshot [dict create roots {} nets {} pin_slrs {}]
    dict for {key targets} $copies {
        set root [dict get $all roots $key]
        dict set snapshot roots $key $root
        dict set snapshot nets $key [dict get $all nets $key]
        foreach sink [dict get $all nets $key before] {
            dict set snapshot pin_slrs $sink [dict get $all pin_slrs $sink]
        }
        dict for {pin sig} [dict get $root inputs] {
            set input [dict get $sig key]
            dict set snapshot nets $input [dict get $all nets $input]
        }
    }
    dict set local snapshot $snapshot
    dict set local graph [graph $snapshot $copies]
    return $local
}
