source [file join [file dirname [info script]] ../../spatial_policy.tcl]
# Pure spatial planning. Names are strings, never persistent native handles.
namespace eval rf {
    variable config [dict create enabled 1 min_fanout 16 branch_limit 96 region_width 2 region_height 2 max_luts 50000]
    variable serial 0
}
proc rf::require {ok message} {if {!$ok} {error $message}}
proc rf::configure {options} {
    variable config
    dict for {key value} $options {
        require [dict exists $config $key] "Unknown regional option: $key"
        require [string is integer -strict $value] "Noninteger regional option: $key"
        if {$key eq "enabled"} {require [expr {$value in {0 1}}] "Invalid enabled flag"} \
        else {require [expr {$value > 0}] "Nonpositive regional option: $key"}
        dict set config $key $value
    }
    require [expr {[dict get $config branch_limit] >= 2 && [dict get $config branch_limit] <= 96}] "branch_limit must be 2..96"
    require [expr {[dict get $config min_fanout] >= 2}] "min_fanout must be >=2"
}
proc rf::sector {position} {
    variable config
    require [regexp {^X([0-9]+)Y([0-9]+)$} [dict get $position cr] unused x y] "Unknown clock region"
    return [list [dict get $position slr] [expr {$x/[dict get $config region_width]}] [expr {$y/[dict get $config region_height]}]]
}
proc rf::allowed_driver {ref pin} {
    if {$ref in {FDRE FDSE} && $pin eq "Q"} {return 1}
    if {[regexp {^LUT[1-6]$} $ref] && $pin eq "O"} {return 1}
    return [expr {[sb::data_input_kind $ref $pin] in {bram_data uram_data}}]
}
proc rf::allowed_sink {ref pin} {
    if {$ref in {FDRE FDSE} && $pin eq "D"} {return 1}
    if {[regexp {^LUT[1-6]$} $ref] && [regexp {^I[0-5]$} $pin]} {return 1}
    if {[regexp {^URAM288(_BASE)?$} $ref] && [regexp {^DIN_[AB]\[[0-9]+\]$} $pin]} {return 1}
    if {[regexp {^RAMB(18|36)E[12]$} $ref] && [regexp {^(DINADIN|DINBDIN|DINPADINP|DINPBDINP|DIADI|DIBDI|DIPADIP|DIPBDIP)\[[0-9]+\]$} $pin]} {return 1}
    return 0
}
proc rf::has_fixed_route {value} {
    # Native Vivado returns the string "{}" for an empty route property.
    return [expr {[string trim $value " \t\r\n{}"] ne ""}]
}
proc rf::known_protected_ip {pin} {
    # Match the observed vendor IP family that rejects ECO with Coretcl 2-76.
    # This is a conservative provenance exclusion, not a general rights detector.
    return [regexp {(^|/)inst/i_synth/} $pin]
}
proc rf::validate_edit_scope {plan} {
    # Reject unsafe saved plans before any regional or inherited ECO mutation.
    foreach root [dict get $plan roots] {
        set driver [dict get $root driver]
        require [expr {![known_protected_ip $driver]}] "Protected IP driver in regional plan: $driver"
        foreach pin [dict get $root sinks] {
            require [expr {![known_protected_ip $pin]}] "Protected IP sink in regional plan: $pin"
        }
    }
}
proc rf::node {kind regions loads} {
    variable serial
    return [dict create name rfd_lut_[incr serial] kind $kind regions [lsort -unique $regions] loads $loads]
}
proc rf::pack {atoms limit} {
    set result {}; set pending {}
    foreach atom $atoms {
        require [expr {[llength $atom] <= $limit}] "A shared-site atom exceeds the branch limit"
        if {[llength $pending]+[llength $atom] > $limit} {lappend result $pending; set pending {}}
        lappend pending {*}$atom
    }
    if {[llength $pending]} {lappend result $pending}
    return $result
}
proc rf::plan_root_reference {driver source sink_rows} {
    variable config
    set limit [dict get $config branch_limit]
    array set buckets {}; array set pin_position {}; array set seen {}; array set regions {}
    set sinks {}
    foreach row $sink_rows {
        lassign $row pin pos
        require [expr {![info exists seen($pin)]}] "Duplicate sink: $pin"
        set seen($pin) 1; set pin_position($pin) $pos
        set region [dict get $pos cr]; set regions($region) 1
        lappend buckets([sector $pos]) $pin
        lappend sinks $pin
    }
    if {[llength $sinks] < [dict get $config min_fanout]} {return [dict create status below_minimum]}
    if {[array size regions] < 2} {return [dict create status one_clock_region]}
    set nodes {}; set frontier {}
    foreach key [lsort -dictionary [array names buckets]] {
        set local $buckets($key); set target_regions {}
        foreach pin $local {lappend target_regions [dict get $pin_position($pin) cr]}
        set target_regions [lsort -unique $target_regions]
        if {[llength $local] > $limit} {
            # Keep a shared site's loads together, and never mix CRs in the leaf tier.
            array unset bycr *; array unset atoms *
            foreach pin $local {
                set pos $pin_position($pin)
                set atom_key [list [dict get $pos cr] [dict get $pos loc]]
                lappend atoms($atom_key) $pin
            }
            foreach atom_key [lsort -dictionary [array names atoms]] {
                lappend bycr([lindex $atom_key 0]) [lsort $atoms($atom_key)]
            }
            set local {}
            foreach cr [lsort -dictionary [array names bycr]] {
                foreach group [pack $bycr($cr) $limit] {
                    set n [node local [list $cr] $group]
                    lappend nodes $n; lappend local [dict get $n name]/I0
                }
            }
            while {[llength $local] > $limit} {
                set next {}
                foreach group [sb::chunks $local $limit] {
                    set n [node local $target_regions $group]
                    lappend nodes $n; lappend next [dict get $n name]/I0
                }
                set local $next
            }
        }
        # The source tier stays near the source, but each output serves one sector.
        set n [node source [list [dict get $source cr]] $local]
        dict set n destination_sector $key
        dict set n destination_regions $target_regions
        lappend nodes $n; lappend frontier [dict get $n name]/I0
    }
    if {[llength $frontier] >= [llength $sinks]} {return [dict create status no_root_reduction]}
    if {[llength $frontier] > $limit} {return [dict create status source_branch_limit]}
    set result [dict create status selected driver $driver source $source sinks [lsort $sinks] nodes $nodes frontier $frontier]
    validate_tree $result
    return $result
}
proc rf::plan_root {driver source sink_rows} {
    variable config
    set limit [dict get $config branch_limit]
    array set seen {}; array set by_sector {}; array set pin_position {}
    set sinks {}
    foreach row $sink_rows {
        lassign $row pin pos
        require [expr {![info exists seen($pin)]}] "Duplicate sink: $pin"
        set seen($pin) 1; set pin_position($pin) $pos
        lappend sinks $pin; lappend by_sector([sector $pos]) $pin
    }
    if {[llength $sinks] < [dict get $config min_fanout]} {return [dict create status below_minimum]}
    # A second pass must not add another tier just because a legal tree is spatially broad.
    if {[llength $sinks] <= $limit} {return [dict create status existing_fanout_sufficient]}
    set nodes {}; set frontier {}; array set helper_regions {}; array set helper_slr {}
    foreach sector [lsort -dictionary [array names by_sector]] {
        array unset atoms *
        foreach pin $by_sector($sector) {
            set pos $pin_position($pin)
            lappend atoms([list [dict get $pos cr] [dict get $pos loc]]) $pin
        }
        set units {}
        foreach key [lsort -dictionary [array names atoms]] {lappend units [lsort $atoms($key)]}
        foreach group [pack $units $limit] {
            # A singleton is connected directly; it does not need a serial identity cell.
            if {[llength $group] == 1} {lappend frontier {*}$group; continue}
            set regions {}
            foreach pin $group {lappend regions [dict get $pin_position($pin) cr]}
            set n [node local [geo::rectangle $regions] $group]
            dict set n movable 1
            dict set n destination_sector $sector
            dict set n destination_regions [lsort -unique $regions]
            set input [dict get $n name]/I0
            set helper_regions($input) [dict get $n regions]
            set helper_slr($input) [lindex $sector 0]
            lappend nodes $n; lappend frontier $input
        }
    }
    # Additional tiers are legal only when the electrical cap actually requires them.
    while {[llength $frontier] > $limit} {
        array unset by_slr *
        foreach pin $frontier {
            if {[info exists helper_slr($pin)]} {set slr $helper_slr($pin)} else {set slr [dict get $pin_position($pin) slr]}
            lappend by_slr($slr) $pin
        }
        set next {}
        foreach slr [lsort [array names by_slr]] {
            foreach group [sb::chunks $by_slr($slr) $limit] {
                if {[llength $group] == 1} {lappend next {*}$group; continue}
                set regions {}
                foreach pin $group {
                    if {[info exists helper_regions($pin)]} {lappend regions {*}$helper_regions($pin)} else {lappend regions [dict get $pin_position($pin) cr]}
                }
                set n [node local [geo::rectangle $regions] $group]
            dict set n movable 1
                set input [dict get $n name]/I0
                set helper_regions($input) [dict get $n regions]; set helper_slr($input) $slr
                lappend nodes $n; lappend next $input
            }
        }
        require [expr {[llength $next] < [llength $frontier]}] "Spatial tree cannot progress without mixing SLRs"
        set frontier $next
    }
    set result [dict create status selected driver $driver source $source sinks [lsort $sinks] nodes $nodes frontier $frontier]
    validate_tree $result
    return $result
}
proc rf::validate_tree {root} {
    variable config
    set limit [dict get $config branch_limit]
    array set edges {}; array set incoming {}; array set originals {}
    foreach pin [dict get $root sinks] {set originals($pin) 1}
    foreach n [dict get $root nodes] {
        set input [dict get $n name]/I0
        require [expr {![info exists edges($input)]}] "Duplicate distribution LUT"
        set edges($input) [dict get $n loads]
        require [expr {[llength $edges($input)] > 0 && [llength $edges($input)] <= $limit}] "Branch fanout out of bounds"
        foreach pin $edges($input) {if {![info exists incoming($pin)]} {set incoming($pin) 0}; incr incoming($pin)}
    }
    set pending [dict get $root frontier]; set recovered {}; array set visited {}
    require [expr {[llength $pending] > 0 && [llength $pending] <= $limit}] "Root fanout out of bounds"
    foreach pin $pending {if {![info exists incoming($pin)]} {set incoming($pin) 0}; incr incoming($pin)}
    foreach pin [array names incoming] {require [expr {$incoming($pin) == 1}] "Multiply driven planned input: $pin"}
    while {[llength $pending]} {
        set next {}
        foreach pin $pending {
            require [expr {![info exists visited($pin)]}] "Cycle or duplicate leaf: $pin"
            set visited($pin) 1
            if {[info exists edges($pin)]} {lappend next {*}$edges($pin)} else {lappend recovered $pin}
        }
        set pending $next
    }
    require [expr {[lsort $recovered] eq [dict get $root sinks]}] "Original sink multiset mismatch"
    foreach pin [array names edges] {require [info exists visited($pin)] "Unreachable distribution LUT: $pin"}
}
