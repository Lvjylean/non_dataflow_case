# Joint input planning uses an immutable per-stage inventory, never a live edit cache.
namespace eval ji {
    variable module_dir [file dirname [info script]]
    variable cells; variable inputs; variable nodes; variable nets
    array set cells {}; array set inputs {}; array set nodes {}; array set nets {}
}
proc ji::comb {ref} {return [regexp {^(LUT[1-6]|MUXF[789])$} $ref]}
proc ji::placed_loads {local key slr} {
    # Position and moved-load counts come from the immutable placed netlist.
    # graph.expected also contains inputs of planned replicas: those cells do
    # not exist yet, and the host planner budgets their new inputs separately.
    set snapshot [dict get $local snapshot];set loads {}
    foreach sink [dict get $snapshot nets $key before] {
        if {[dict get $snapshot pin_slrs $sink] eq $slr} {lappend loads $sink}
    }
    sb::require [expr {[llength $loads]>0}] "No placed receivers for candidate: $key@$slr"
    return $loads
}
proc ji::describe {name} {
    variable cells
    if {[info exists cells($name)]} {return $cells($name)}
    set obj [sb::cell $name]; set ref [sb::ref $name]; set p [sb::position $name]
    set cr [get_property NAME [get_clock_regions -of_objects [get_sites [list [dict get $p loc]]]]]
    sb::require [regexp {^X([0-9]+)Y([0-9]+)$} $cr unused x y] "Unknown CR: $name $cr"
    set cells($name) [dict create name $name ref $ref slr [dict get $p slr] x $x y $y]
    if {$ref in {FDRE FDSE}} {
        set clocks [get_clocks -quiet -of_objects [sb::pin $name/C]]
        if {[llength $clocks]==1} {dict set cells($name) period [get_property PERIOD $clocks]} else {dict set cells($name) period ""}
    } else {dict set cells($name) period ""}
    return $cells($name)
}
proc ji::record {name} {
    variable inputs; variable nodes; variable nets
    if {[info exists inputs($name)]} {return}
    set desc [describe $name]; set ref [dict get $desc ref]
    set is {}
    foreach pin [sb::names [get_pins -of_objects [sb::cell $name] -filter {IS_LEAF == 1 && DIRECTION == IN}]] {
        set sig [lb::describe_signal $pin]
        dict set is [file tail $pin] $sig
        set key [dict get $sig key]
        if {![info exists nets($key)]} {
            set loads {}; if {[dict get $sig kind] eq "ordinary"} {set loads [sb::loads [dict get $sig anchor]]}
            set nets($key) [dict merge $sig [dict create before $loads]]
        }
        if {[dict get $sig kind] eq "ordinary" && [lindex [dict get $sig signal] 0] eq "drivers"} {describe [file dirname $key]}
    }
    set inputs($name) $is
    if {[comb $ref] || $ref in {FDRE FDSE}} {
        set op [expr {$ref in {FDRE FDSE} ? "Q" : "O"}]; set key $name/$op
        set nodes($name) [dict create cell $name ref $ref pin $op slr [dict get $desc slr] inputs $is config [sb::config $name]]
        if {![info exists nets($key)]} {set nets($key) [dict create key $key kind ordinary anchor $key slr [dict get $desc slr] signal [list drivers [list $key]] before [sb::loads $key]]}
    }
}
proc ji::expand {name depth seenvar activevar} {
    upvar 1 $seenvar seen $activevar active
    variable inputs
    set ref [dict get [describe $name] ref]
    if {![comb $ref]} {
        if {![regexp {^(FDRE|FDSE|RAMB(18|36)E[12]|URAM288(_BASE)?)$} $ref]} {error "unsupported_cone_boundary:$ref"}
        return
    }
    if {[dict exists $active $name]} {error "combinational_cycle:$name"}
    if {[dict exists $seen $name]} {return}
    if {$depth>16 || [dict size $seen]>=2048} {error "cone_inventory_budget"}
    if {[rf::known_protected_ip $name] || [rf::protected_ancestor $name] ne ""} {error "protected_cone"}
    set net [get_nets -of_objects [sb::pin $name/O]]
    if {[sb::one_bit [get_property IS_ROUTE_FIXED $net]] || [rf::has_fixed_route [get_property FIXED_ROUTE $net]]} {error "fixed_cone_route"}
    dict set active $name 1; record $name; dict set seen $name 1
    dict for {pin sig} $inputs($name) {
        if {[dict get $sig kind] eq "ordinary"} {
            if {[lindex [dict get $sig signal] 0] ne "drivers"} {error "unpositioned_port_boundary"}
            expand [file dirname [dict get $sig key]] [expr {$depth+1}] seen active
        } elseif {[dict get $sig kind] ne "constant"} {error "clock_in_combination"}
    }
    dict unset active $name
}
proc ji::slacks_reference {pins path} {
    set observed {}; set pins [lsort -unique $pins]
    foreach batch [sb::chunks $pins 512] {
        set objects [get_pins -quiet $batch]
        foreach type {max min} {
            foreach p [get_timing_paths -to $objects -delay_type $type -max_paths [llength $batch] -nworst 1] {
                set ep [get_property ENDPOINT_PIN $p]; set value [get_property SLACK $p]
                if {![dict exists $observed $ep $type] || $value<[dict get $observed $ep $type]} {dict set observed $ep $type $value}
                if {$type eq "max"} {dict set observed $ep requirement [get_property REQUIREMENT $p]}
            }
        }
    }
    set f [open $path w];puts $f "pin\tmax\tmin\trequirement"
    foreach pin $pins {
        set values [list $pin]
        foreach type {max min requirement} {lappend values [expr {[dict exists $observed $pin $type] ? [dict get $observed $pin $type] : ""}]}
        puts $f [join $values \t]
    }
    close $f
    return $observed
}
source [file join [file dirname [info script]] timing_fast.tcl]
proc ji::slacks {pins path} {
    if {[info exists ::env(JI_TIMING_MODE)] && $::env(JI_TIMING_MODE) eq "reference"} {
        return [jif::timed $path reference [list slacks_reference $pins $path]]
    }
    return [jif::path_slacks $pins $path]
}
proc ji::enrich {local out} {
    variable module_dir; variable cells; variable inputs; variable nodes; variable nets
    foreach var {cells inputs nodes nets} {array unset $var *}
    set cf [open $out/ji_candidates.tsv w];puts $cf "id\tkey\treplica\tref\ttarget\tx\ty\tloads\tdriver\tdriver_cell\tstatus"
    set cones [open $out/ji_cones.tsv w];puts $cones "key\tcell"
    set endpoints {}; set snapshot [dict get $local snapshot]
    dict for {key targets} [dict get $local copies] {
        set root [dict get $snapshot roots $key];set name [dict get $root cell];set ref [dict get $root ref]
        set status supported;set seen {};set active {};set driver ""
        if {$ref ni {FDRE FDSE}} {set status standalone_LUT_requires_separate_input_timing_model} \
        elseif {[catch {
            record $name
            set ds [dict get $inputs($name) D]
            if {[dict get $ds kind] ne "ordinary" || [lindex [dict get $ds signal] 0] ne "drivers"} {error "unsupported_D_boundary"}
            set driver [dict get $ds key]
            expand [file dirname $driver] 0 seen active
            dict for {pin sig} $inputs($name) {if {$pin in {D CE R S}} {lappend endpoints $name/$pin}}
        } why]} {set status $why}
        foreach c [dict keys $seen] {puts $cones "$key\t$c"}
        dict for {slr replica} $targets {
            set x 0.0;set y 0.0;set n 0
            foreach sink [placed_loads $local $key $slr] {
                set p [describe [file dirname $sink]]
                set x [expr {$x+[dict get $p x]}];set y [expr {$y+[dict get $p y]}];incr n
            }
            sb::require [expr {$n>0}] "Empty replica group"
            puts $cf [join [list "$key@$slr" $key $replica $ref $slr [expr {$x/$n}] [expr {$y/$n}] $n $driver [file dirname $driver] $status] \t]
        }
    }
    close $cf;close $cones
    slacks $endpoints $out/ji_slacks.tsv
    set f [open $out/ji_cells.tsv w];puts $f "name\tref\tslr\tx\ty\tperiod"
    foreach name [array names cells] {set values {};foreach key {name ref slr x y period} {lappend values [dict get $cells($name) $key]};puts $f [join $values \t]};close $f
    set f [open $out/ji_edges.tsv w];puts $f "cell\tpin\tkey\tkind\tsource_cell"
    foreach name [array names inputs] {
        dict for {pin sig} $inputs($name) {
            set source "";if {[dict get $sig kind] eq "ordinary" && [lindex [dict get $sig signal] 0] eq "drivers"} {set source [file dirname [dict get $sig key]]}
            puts $f [join [list $name $pin [dict get $sig key] [dict get $sig kind] $source] \t]
        }
    };close $f
    set f [open $out/ji_nets.tsv w];puts $f "key\tfanout"
    foreach key [array names nets] {if {[dict get $nets($key) kind] eq "ordinary"} {puts $f "$key\t[llength [dict get $nets($key) before]]"}};close $f
    report_utilization -slr -file $out/ji_utilization_slr.rpt
    # The production flow currently targets UltraScale+ CLB architecture.
    set part [get_property PART [current_design]]
    sb::require [regexp {^xc[vu]} $part] "Unsupported CLB capacity architecture: $part"
    set f [open $out/ji_capacity.tsv w];puts $f "slr\tkind\tcapacity"
    foreach slr [get_slrs] {
        set n [llength [get_sites -of_objects $slr -filter {SITE_TYPE == SLICEL || SITE_TYPE == SLICEM}]]
        foreach kind {LUT FF MUXF7 MUXF8 MUXF9} factor {8 16 4 2 1} {puts $f "[get_property NAME $slr]\t$kind\t[expr {$n*$factor}]"}
    };close $f
    set args [list python3 $module_dir/joint_input.py $out]
    foreach envname {JI_MARGIN JI_MAX_ADDED JI_PER_ENDPOINT} option {--margin --max-added --per-endpoint} {
        if {[info exists ::env($envname)]} {lappend args $option $::env($envname)}
    }
    if {[info exists ::env(JI_EXCLUDE)] && $::env(JI_EXCLUDE) ne ""} {lappend args --exclude $::env(JI_EXCLUDE)}
    puts [exec {*}$args];source $out/joint_plan.tcl
    set copies [dict get $local copies]
    dict for {key targets} $copies {
        dict for {slr name} $targets {
            if {[lsearch -exact $ji_keep "$key@$slr"]<0} {dict unset copies $key $slr}
        }
        if {![dict size [dict get $copies $key]]} {dict unset copies $key}
    }
    dict set local copies $copies
    set local [lb::edit_scope $local];set snapshot [dict get $local snapshot]
    # Input cones never commandeer original sinks; only new copies use them.
    dict for {name item} $ji_aux {
        set key [dict get $item key];set c [file dirname $key]
        dict set snapshot roots $key $nodes($c)
        set keys [list $key];dict for {pin sig} $inputs($c) {lappend keys [dict get $sig key]}
        foreach nk $keys {
            dict set snapshot nets $nk $nets($nk)
        }
    }
    set graph [lb::graph $snapshot $copies]
    dict for {name item} $ji_aux {
        dict set graph replicas $name [dict create key [dict get $item key] slr [dict get $item slr]]
        dict set graph expected $name/O {}
    }
    dict for {pin source} $ji_links {
        if {[dict exists $graph new_inputs $pin]} {
            set old [dict get $graph new_inputs $pin]
            if {[dict exists $graph expected $old]} {
                set v [dict get $graph expected $old];set index [lsearch -exact $v $pin]
                sb::require [expr {$index>=0}] "Missing old candidate input"
                dict set graph expected $old [lreplace $v $index $index]
            }
        }
        dict set graph new_inputs $pin $source
        if {[dict exists $graph expected $source]} {
            set sinks [dict get $graph expected $source];lappend sinks $pin
            dict set graph expected $source $sinks
        }
    }
    # dict lappend does not accept nested paths: normalize expected via local values.
    dict for {key sinks} [dict get $graph expected] {
        sb::require [expr {[llength $sinks]==[llength [lsort -unique $sinks]]}] "Duplicate joint sink: $key"
        sb::require [expr {[llength $sinks]<100}] "Joint projected fanout exceeds budget: $key"
        dict set graph expected $key [lsort $sinks]
    }
    dict set local snapshot $snapshot;dict set local graph $graph
    dict set local joint_input [dict create schema joint-input-v1 accepted $ji_keep aux $ji_aux hints $ji_hints]
    return $local
}
proc ji::hint_constraints {local} {
    if {![dict exists $local joint_input hints]} {return $local}
    # A cell has one direct Pblock membership. Do not replace a hard SLR
    # assignment with a soft child assignment and infer physical containment.
    # Keep coordinate hints as plan metadata, with whole-SLR placement freedom.
    dict for {name item} [dict get $local joint_input hints] {
        set slr [dict get $item slr]
        lb::bind $name $slr
        set pb localrep_$slr
        dict set local joint_input hints $name binding hard_slr_only
        dict set local joint_input hints $name pblock $pb
        dict set local joint_input hints $name ranges [lsort [get_property GRID_RANGES [get_pblocks $pb]]]
        sb::require [expr {[get_property PBLOCK [sb::cell $name]] eq $pb}] "Direct SLR binding lost: $name"
    }
    return $local
}

proc ji::in_parent {cell parent} {
    foreach pb [get_pblocks -quiet -of_objects [sb::cell $cell]] {
        set name [get_property NAME $pb];set seen {}
        while {$name ne "" && $name ne "ROOT" && [lsearch -exact $seen $name]<0} {
            if {$name eq $parent} {return 1}
            lappend seen $name
            set name [get_property PARENT [get_pblocks $name]]
        }
    }
    return 0
}
proc ji::capture_guard {plan out} {
    set local [dict get $plan local_broadcast];set snapshot [dict get $local snapshot];set graph [dict get $local graph]
    set sources {};set pins {};set newpins {};set folder $out/joint_before
    file mkdir $folder
    dict for {key sinks} [dict get $graph expected] {
        if {![dict exists $snapshot nets $key]} {continue}
        set before [dict get $snapshot nets $key before]
        if {$before ne $sinks && [lindex [dict get $snapshot nets $key signal] 0] eq "drivers"} {lappend sources $key}
    }
    foreach batch [sb::chunks $sources 256] {
        lappend pins {*}[sb::names [all_fanout -flat -endpoints_only -from [get_pins $batch]]]
    }
    set f [open $folder/mapping.tsv w];puts $f "pin\toriginal\towner"
    dict for {key targets} [dict get $local copies] {
        set cell [file dirname $key];set root [dict get $snapshot roots $key]
        if {[dict get $root ref] ni {FDRE FDSE}} {continue}
        dict for {target replica} $targets {
            dict for {pin sig} [dict get $root inputs] {
                if {$pin in {D CE R S}} {
                    lappend pins $cell/$pin; lappend newpins $replica/$pin
                    puts $f "$replica/$pin\t$cell/$pin\t$key@$target"
                }
            }
        }
    };close $f
    foreach p [get_timing_paths -max_paths 1000 -nworst 1] {lappend pins [get_property ENDPOINT_PIN $p]}
    set pins [lsort -unique $pins]
    jif::guard_slacks $pins $folder/slacks.tsv
    report_timing_summary -delay_type min_max -file $folder/timing_summary.rpt
    dict set plan joint_guard [dict create before $folder pins $pins newpins $newpins]
    return $plan
}
proc ji::placed_guard {plan out} {
    variable module_dir
    set guard [dict get $plan joint_guard];set folder $out/joint_placed
    file mkdir $folder
    jif::guard_slacks [concat [dict get $guard pins] [dict get $guard newpins]] $folder/slacks.tsv
    report_timing_summary -delay_type min_max -file $folder/timing_summary.rpt
    set verdict [exec python3 $module_dir/joint_gate.py [dict get $guard before] $folder]
    if {$verdict ne "ACCEPT"} {
        set f [open $out/REJECTED_BEFORE_ROUTE w];puts $f "Placed input/output timing guard rejected this candidate batch; no full routing performed.";close $f
        return -code error -errorcode {JI TIMING_REJECTED} "Joint input timing guard rejected the placed batch"
    }
    set f [open $folder/PASS w];puts $f "Placed joint input/output setup and hold protection PASS";close $f
}
