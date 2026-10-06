source [file join [file dirname [info script]] execution.tcl]
source [file join [file dirname [info script]] policy.tcl]
source [file join [file dirname [info script]] structural.tcl]
namespace eval sb {
    variable pin_objects
    array set pin_objects {}
    variable cell_objects
    array set cell_objects {}
    variable positions
    array set positions {}
    variable site_slrs
    array set site_slrs {}
    variable protect_cells {}
    variable protect_nets {}
    variable protected_net_seen
    array set protected_net_seen {}
    variable track {}
    variable tracked_net_keys
    array set tracked_net_keys {}
    variable tracked_driver_keys
    array set tracked_driver_keys {}
    variable budget 512
    variable selection structure
    variable refs
    array set refs {}
    variable signal_cache {}
    variable unlocked_signals {}
}
proc sb::values {property objects} {
    if {![llength $objects]} {return {}}
    set v [get_property $property $objects]
    if {[llength $objects] == 1} {return [list $v]}
    return [lrange [split "__scalar__\n[join $v \n]" \n] 1 end]
}
proc sb::spatial_cache {} {
    variable positions
    variable signal_cache
    array unset positions *
    set signal_cache {}
}
proc sb::prefetch {cell_names} {
    variable positions
    variable site_slrs
    variable refs
    set missing {}
    foreach c [lsort -unique $cell_names] {
        if {![info exists positions($c)]} {lappend missing $c}
    }
    if {![llength $missing]} {return}
    set cells {}
    foreach name $missing {lappend cells [cell $name]}
    foreach name [values NAME $cells] loc [values LOC $cells] bel [values BEL $cells] ref [values REF_NAME $cells] {
        set refs($name) $ref
        if {$loc eq ""} {continue}
        if {![info exists site_slrs($loc)]} {
            set slrs [names [get_slrs -of_objects [get_sites [list $loc]]]]
            require [expr {[llength $slrs] == 1}] "Ambiguous SLR: $loc"
            set site_slrs($loc) [lindex $slrs 0]
        }
        set positions($name) [dict create loc $loc bel $bel slr $site_slrs($loc)]
    }
}
proc sb::ref {name} {
    variable refs
    if {![info exists refs($name)]} {set refs($name) [get_property REF_NAME [cell $name]]}
    return $refs($name)
}

proc sb::names {objects} {
    if {![llength $objects]} {return {}}
    return [split [join [get_property NAME $objects] \n] \n]
}
proc sb::cell {name} {
    variable cell_objects
    if {[info exists cell_objects($name)]} {return $cell_objects($name)}
    set c [get_cells -quiet [list $name]]
    require [expr {[llength $c] == 1}] "Missing/ambiguous cell: $name"
    return $c
}
proc sb::pin {name} {
    variable cell_objects
    variable pin_objects
    if {[array size cell_objects]} {
        if {![info exists pin_objects($name)]} {
            set objects [get_pins -quiet -of_objects [cell [file dirname $name]]]
            foreach obj $objects key [names $objects] {set pin_objects($key) $obj}
        }
        require [info exists pin_objects($name)] "Missing pin: $name"
        return $pin_objects($name)
    }
    set p [get_pins -quiet [list $name]]
    require [expr {[llength $p] == 1}] "Missing/ambiguous pin: $name"
    return $p
}
proc sb::canonical {p} {
    set n [get_nets -quiet -top_net_of_hierarchical_group -segments -of_objects [pin $p]]
    require [expr {[llength $n] == 1}] "Expected one connected signal: $p"
    return [get_property NAME $n]
}
proc sb::net_at {p} {get_property NAME [get_nets -of_objects [pin $p]]}
proc sb::loads {p} {
    return [lsort -unique [names [get_pins -quiet -of_objects \
        [get_nets -segments -of_objects [pin $p]] -filter {DIRECTION == IN && IS_LEAF == 1}]]]
}
proc sb::drivers {p} {
    return [lsort -unique [names [get_pins -quiet -of_objects \
        [get_nets -segments -of_objects [pin $p]] -filter {DIRECTION == OUT && IS_LEAF == 1}]]]
}
proc sb::signal {p} {
    variable signal_cache
    set n [get_nets -of_objects [pin $p]]
    set type [get_property TYPE $n]
    if {$type in {GROUND POWER}} {return [list constant $type]}
    if {[file tail $p] eq "C" && [get_property REF_NAME [cell [file dirname $p]]] in {FDRE FDSE}} {
        return [list clock [canonical $p]]
    }
    set key [canonical $p]
    if {[dict exists $signal_cache $key]} {return [dict get $signal_cache $key]}
    set d [drivers $p]
    if {[llength $d]} {set result [list drivers $d]} else {
        set result [list ports [lsort [names [get_ports -quiet -of_objects \
            [get_nets -segments -of_objects [pin $p]]]]]]
    }
    dict set signal_cache $key $result
    return $result
}
proc sb::position {name} {
    variable positions
    variable site_slrs
    if {[info exists positions($name)]} {return $positions($name)}
    set c [cell $name]
    set loc [get_property LOC $c]
    require [expr {$loc ne ""}] "Unplaced source or load: $name"
    if {![info exists site_slrs($loc)]} {
        set sites [get_sites -of_objects $c]
        set slrs [names [get_slrs -of_objects $sites]]
        require [expr {[llength $slrs] == 1}] "Ambiguous site SLR: $name"
        set site_slrs($loc) [lindex $slrs 0]
    }
    set v [dict create loc $loc bel [get_property BEL $c] slr $site_slrs($loc)]
    set positions($name) $v
    return $v
}
proc sb::config {name} {
    set c [cell $name]
    set ref [get_property REF_NAME $c]
    if {$ref in {FDRE FDSE}} {
        set reset [expr {$ref eq "FDRE" ? "R" : "S"}]
        set result {}
        foreach p [list INIT IS_C_INVERTED IS_D_INVERTED IS_${reset}_INVERTED] {
            set default [expr {$p eq "INIT" && $ref eq "FDSE" ? 1 : 0}]
            set value [one_bit [get_property $p $c] $default]
            if {$p eq "INIT"} {set value "1'b$value"}
            dict set result $p $value
        }
        return $result
    }
    if {[regexp {^LUT[1-6]$} $ref]} {return [dict create INIT [string tolower [get_property INIT $c]]]}
    if {$ref in {MUXF7 MUXF8 MUXF9}} {return {}}
    error "Unsupported primitive for replication: $ref $name"
}
proc sb::inputs {name} {
    set result {}
    foreach p [names [get_pins -of_objects [cell $name] -filter {DIRECTION == IN && IS_LEAF == 1}]] {
        dict set result [file tail $p] [dict create net [net_at $p] signal [signal $p]]
    }
    return $result
}
proc sb::save {plan path} {
    set started [clock microseconds]
    set f [open ${path}.tmp w]
    puts $f {set sb_plan {}}
    dict for {key value} $plan {puts $f [list dict set sb_plan $key $value]}
    close $f
    file rename -force ${path}.tmp $path
    puts "PLAN_WRITE [clock microseconds] bytes=[file size $path] elapsed_us=[expr {[clock microseconds]-$started}]"
}
proc sb::counts {} {
    return [dict create ff [llength [get_cells -hier -filter {IS_PRIMITIVE == 1 && REF_NAME =~ FD* && NAME !~ sllph_*}]] \
        lut [llength [get_cells -hier -filter {IS_PRIMITIVE == 1 && REF_NAME =~ LUT*}]] \
        mux [llength [get_cells -hier -filter {IS_PRIMITIVE == 1 && REF_NAME =~ MUXF*}]]]
}
proc sb::scan {out path_limit min_fanout} {
    variable budget
    variable selection
    require [expr {![llength [get_cells -quiet sbeco_*]]}] "This checkpoint already contains this ECO"
    require [expr {![llength [get_pblocks -quiet sbeco_*]]}] "ECO pblocks already exist"
    set plan [dict create schema slr-broadcast-eco-v1 counts_before [counts] \
        path_limit $path_limit min_fanout $min_fanout data {} ce {} fixed {} q_candidates {}]
    dict set plan selection $selection
    if {$selection eq "structure"} {
        set seeds [structural_seeds $out $min_fanout]
        set candidates [dict get $seeds data_candidates]
        set ce_targets [dict get $seeds ce_targets]
        dict set plan sampled_paths 0
        dict set plan structural_net_roots [dict get $seeds net_roots]
    } else {
    set paths [get_timing_paths -delay_type max -max_paths $path_limit -nworst $path_limit -unique_pins]
    set source_families {}
    set ce_families {}
    set seen_endpoints {}
    foreach tp $paths {
        set sp [get_property STARTPOINT_PIN $tp]
        set ep [get_property ENDPOINT_PIN $tp]
        set sc [file dirname $sp]
        if {[get_property REF_NAME [cell $sc]] in {FDRE FDSE}} {dict set source_families [family $sc] 1}
        if {[file tail $ep] eq "CE" && ![dict exists $seen_endpoints $ep]} {
            dict set seen_endpoints $ep 1
            set ds [drivers $ep]
            if {[llength $ds] == 1} {
                set dc [file dirname [lindex $ds 0]]
                if {[regexp {^LUT[1-6]$} [get_property REF_NAME [cell $dc]]] &&
                    [dict get [position $dc] slr] ne [dict get [position [file dirname $ep]] slr]} {
                    dict set ce_families [family [file dirname $ep]] 1
                }
            }
        }
    }
    dict set plan sampled_paths [llength $paths]
    dict set plan source_families [dict keys $source_families]
    dict set plan ce_families [dict keys $ce_families]
    set all [names [get_cells -hier -filter {IS_PRIMITIVE == 1 && (REF_NAME == FDRE || REF_NAME == FDSE)}]]
    set candidates {}
    set ce_targets {}
    foreach c $all {
        set family [family $c]
        if {[dict exists $source_families $family]} {lappend candidates $c}
        if {[dict exists $ce_families $family]} {dict set ce_targets $c [dict get [position $c] slr]}
    }
    }
    set report [open $out/candidates.tsv w]
    puts $report "cell\tstatus\treason\tq_loads\tslrs\td_source_kind\td_driver"
    flush $report
    puts "SBECO_SCAN expanded_data_candidates=[llength $candidates] expanded_ce_targets=[dict size $ce_targets]"
    flush stdout
    set copies 0
    set candidate_index 0
    foreach c [lsort $candidates] {
        incr candidate_index
        if {$candidate_index % 16 == 1} {puts "SBECO_CANDIDATE index=$candidate_index cell=$c"; flush stdout; flush $report}
        set why ""
        set qloads [loads $c/Q]
        if {[llength $qloads] < $min_fanout} {
            puts $report "$c\tskip\tbelow_min_fanout\t[llength $qloads]\t"
            continue
        }
        # Reject unsupported data shapes before querying shared clock inputs.
        set ddriver [signal $c/D]
        if {[lindex $ddriver 0] ne "drivers" || [llength [lindex $ddriver 1]] != 1} {
            puts $report "$c\tskip\tD_not_single_supported_driver\t[llength $qloads]\t\tunsupported\t"
            continue
        }
        set dp [lindex [lindex $ddriver 1] 0]
        set dkind [data_input_kind [ref [file dirname $dp]] [file tail $dp]]
        if {$dkind eq "unsupported"} {
            puts $report "$c\tskip\tD_unsupported_source\t[llength $qloads]\t\t$dkind\t$dp"
            continue
        }
        set ref [get_property REF_NAME [cell $c]]
        set rst [expr {$ref eq "FDRE" ? "R" : "S"}]
        if {[lindex [signal $c/$rst] 0] ne "constant"} {
            puts $report "$c\tskip\tnonconstant_reset_or_set\t[llength $qloads]\t\t$dkind\t$dp"
            continue
        }
        set groups {}
        set helpers {}
        foreach p $qloads {
            set hc [file dirname $p]
            set h [cell $hc]
            if {[get_property REF_NAME $h] ne "LUT1" || [file tail $p] ne "I0" ||
                [string tolower [get_property INIT $h]] ne "2'h2"} {set why non_identity_Q_branch; break}
            set leaves [loads $hc/O]
            set slrs {}
            set leaf_cells {}
            foreach lp $leaves {lappend leaf_cells [file dirname $lp]}
            prefetch $leaf_cells
            if {![llength $leaves]} {set why empty_helper; break}
            foreach lp $leaves {
                set lc [file dirname $lp]
                set lr [ref $lc]
                set leafpin [file tail $lp]
                if {!(($lr in {FDRE FDSE} && $leafpin eq "D") ||
                    ([string match URAM* $lr] && [regexp {^DIN_[AB]\[} $leafpin]))} {
                    set why non_data_leaf; break
                }
                lappend slrs [dict get [position $lc] slr]
            }
            if {$why ne ""} {break}
            set slrs [lsort -unique $slrs]
            if {[llength $slrs] != 1} {set why helper_spans_SLRs; break}
            set target [lindex $slrs 0]
            if {[dict get [position $hc] slr] ne $target} {set why helper_outside_leaf_SLR; break}
            dict lappend groups $target $p
            dict set helpers $hc [dict create position [position $hc] leaves $leaves config [config $hc]]
        }
        set source [dict get [position $c] slr]
        if {$why eq "" && [dict size $groups] < 2} {set why single_SLR_Q_tree}
        if {$why eq "" && ![dict exists $groups $source]} {set why no_local_Q_group}
        if {$why eq ""} {
            dict for {slr pins} $groups {
                if {[llength $pins] < 4 || [llength $pins] > 99} {set why group_outside_4_to_99; break}
            }
        }
        if {$why ne ""} {
            puts $report "$c\tskip\t$why\t[llength $qloads]\t[join [dict keys $groups] ,]\t$dkind\t$dp"
            continue
        }
        set input [inputs $c]
        set replicas {}
        dict for {slr pins} $groups {
            if {$slr eq $source} {continue}
            incr copies
            require [expr {$copies <= $budget}] "Replica budget exceeded; inspect the plan before increasing it"
            dict set replicas $slr [format sbeco_ff_%04d_%s $copies $slr]
        }
        dict set plan data $c [dict create ref $ref config [config $c] inputs $input d_source_kind $dkind d_driver $dp \
            source_slr $source groups $groups replicas $replicas helpers $helpers]
        dict for {h item} $helpers {dict set plan fixed $h [dict get $item position]}
        dict set ce_targets $c $source
        puts $report "$c\tselected\tlocal_data_broadcast\t[llength $qloads]\t[join [dict keys $groups] ,]\t$dkind\t$dp"
        flush $report
    }
    close $report
    dict set plan ff_added $copies
    # Build CE requests from existing critical endpoint families and all data copies.
    set requests {}
    dict for {c slr} $ce_targets {dict lappend requests [canonical $c/CE] [list $c/CE $slr $c/CE]}
    dict for {c item} [dict get $plan data] {
        dict for {slr replica} [dict get $item replicas] {
            dict lappend requests [canonical $c/CE] [list $replica/CE $slr $c/CE]
        }
    }
    set cr [open $out/ce_candidates.tsv w]
    puts $cr "driver\tsource_slr\ttarget_slr\tloads\tboundary_gain\tstatus"
    set lut_added 0
    dict for {net reqs} $requests {
        set origin [lindex [lindex $reqs 0] 2]
        set ds [drivers $origin]
        if {[llength $ds] != 1} {continue}
        set driver [lindex $ds 0]
        set c [file dirname $driver]
        set ref [get_property REF_NAME [cell $c]]
        if {![regexp {^LUT[1-6]$} $ref] || [file tail $driver] ne "O"} {
            puts $cr "$driver\t\t\t[llength $reqs]\t\tskip_non_LUT_CE_driver"
            continue
        }
        set source [dict get [position $c] slr]
        set input [inputs $c]
        set input_slrs {}
        set unsafe 0
        dict for {p value} $input {
            set sig [dict get $value signal]
            if {[lindex $sig 0] eq "constant"} {continue}
            if {[lindex $sig 0] ne "drivers" || [llength [lindex $sig 1]] != 1} {set unsafe 1; break}
            set dc [file dirname [lindex [lindex $sig 1] 0]]
            set dr [get_property REF_NAME [cell $dc]]
            if {![regexp {^(LUT[1-6]|FDRE|FDSE)$} $dr]} {set unsafe 1; break}
            lappend input_slrs [dict get [position $dc] slr]
        }
        if {$unsafe} {
            puts $cr "$driver\t$source\t\t[llength $reqs]\t\tskip_special_or_unknown_CE_upstream"
            continue
        }
        set groups {}
        foreach request $reqs {
            lassign $request sink slr unused
            if {$slr ne $source} {dict lappend groups $slr $sink}
        }
        dict for {slr pins} $groups {
            set pins [lsort -unique $pins]
            set gain [ce_gain $source $slr $input_slrs [llength $pins]]
            if {$gain <= 0} {
                puts $cr "$driver\t$source\t$slr\t[llength $pins]\t$gain\tskip_nonpositive_gain"
                continue
            }
            foreach chunk [chunks $pins 99] {
                incr lut_added
                set name [format sbeco_ce_%04d_%s $lut_added $slr]
                dict set plan ce $name [dict create original $c ref $ref config [config $c] inputs $input \
                    driver $driver source_slr $source target_slr $slr loads $chunk]
            }
            puts $cr "$driver\t$source\t$slr\t[llength $pins]\t$gain\tselected"
        }
    }
    close $cr
    dict set plan lut_added $lut_added
    dict set plan no_op [expr {$copies+$lut_added == 0}]
    # Native object handles are valid only during the read-only scan.
    variable cell_objects
    array unset cell_objects *
    variable pin_objects
    array unset pin_objects *
    save $plan $out/plan.tcl
    puts "SBECO_PLAN ff_added=$copies lut_added=$lut_added roots=[dict size [dict get $plan data]] fixed_helpers=[dict size [dict get $plan fixed]]"
    return $plan
}
proc sb::unlock_cell {name} {
    variable protect_cells
    while {$name ni {. / {}}} {
        if {![dict exists $protect_cells $name]} {
            set c [cell $name]
            dict set protect_cells $name [get_property DONT_TOUCH $c]
            if {[one_bit [dict get $protect_cells $name]]} {set_property DONT_TOUCH false $c}
        }
        set name [file dirname $name]
    }
}
proc sb::reset_edit_state {} {
    variable protect_cells
    variable protect_nets
    variable protected_net_seen
    variable track
    variable tracked_net_keys
    variable tracked_driver_keys
    variable unlocked_signals
    set protect_cells {}
    set protect_nets {}
    array unset protected_net_seen *
    set track {}
    array unset tracked_net_keys *
    array unset tracked_driver_keys *
    set unlocked_signals {}
}
proc sb::unlock_net {p {track_loads 1}} {
    variable protect_nets
    variable protected_net_seen
    variable track
    variable tracked_net_keys
    variable tracked_driver_keys
    variable unlocked_signals
    set canonical [canonical $p]
    if {$track_loads && ![dict exists $track $canonical]} {
        dict set track $canonical [dict create anchor $p before [loads $p] added {} removed {}]
        foreach driver [drivers $p] {
            require [expr {![info exists tracked_driver_keys($driver)] || $tracked_driver_keys($driver) eq $canonical}] \
                "Ambiguous original tracking key for driver: $driver"
            set tracked_driver_keys($driver) $canonical
        }
    }
    if {$track_loads} {set tracked_net_keys($canonical) $canonical} \
    elseif {![info exists tracked_net_keys($canonical)]} {set tracked_net_keys($canonical) ""}
    set kind [expr {$track_loads ? "ordinary" : "clock_or_constant"}]
    set cachekey [list [expr {$track_loads ? $canonical : [net_at $p]}] $kind]
    if {[dict exists $unlocked_signals $cachekey]} {return $canonical}
    # C and constant inputs only add a load at the existing segment. Do not
    # enumerate or write protection on unrelated global clock/constant branches.
    if {$track_loads} {set objects [get_nets -segments -of_objects [pin $p]]} \
    else {set objects [get_nets -of_objects [pin $p]]}
    set change {}
    foreach n [values NAME $objects] v [values DONT_TOUCH $objects] {
        if {[one_bit $v] && ![info exists protected_net_seen($n)]} {
            dict set protect_nets $n $v
            set protected_net_seen($n) 1
            lappend change $n
        }
    }
    if {[llength $change]} {set_property DONT_TOUCH false [get_nets $change]}
    dict set unlocked_signals $cachekey 1
    return $canonical
}
proc sb::tracking_key {p} {
    variable tracked_net_keys
    variable tracked_driver_keys
    set canonical [canonical $p]
    if {[info exists tracked_net_keys($canonical)]} {return $tracked_net_keys($canonical)}
    # Constant roots can also be renamed by hierarchical connections. Keep the
    # original constant exclusion using the native type, never a name pattern.
    set type [get_property TYPE [get_nets -of_objects [pin $p]]]
    if {$type in {GROUND POWER}} {
        set tracked_net_keys($canonical) ""
        return ""
    }
    # A hierarchical connection can introduce a new top segment. Resolve that
    # alias once through the unchanged leaf driver, then use the array cache.
    set keys {}
    foreach driver [drivers $p] {
        if {[info exists tracked_driver_keys($driver)]} {lappend keys $tracked_driver_keys($driver)}
    }
    set keys [lsort -unique $keys]
    require [expr {[llength $keys] == 1}] "Untracked or ambiguous edited signal: $p ($canonical)"
    set tracked_net_keys($canonical) [lindex $keys 0]
    return $tracked_net_keys($canonical)
}
proc sb::track_change {key kind p} {
    variable track
    if {[dict exists $track $key]} {
        set v [dict get $track $key $kind]
        lappend v $p
        dict set track $key $kind $v
    }
}
proc sb::connect_input {source_pin dest_pin} {
    set key [tracking_key $source_pin]
    connect_net -hierarchical -net [get_nets -of_objects [pin $source_pin]] -objects [pin $dest_pin]
    track_change $key added $dest_pin
}
proc sb::rewire {sink newnet} {
    set key [tracking_key $sink]
    disconnect_net -net [get_nets -of_objects [pin $sink]] -pinlist [pin $sink]
    track_change $key removed $sink
    connect_net -hierarchical -net [get_nets [list $newnet]] -objects [pin $sink]
}
proc sb::rewire_many {sinks newnet} {
    if {!$::execopt::enabled} {
        foreach sink $sinks {rewire $sink $newnet}
        return
    }
    set order {}; set key_order {}
    array set groups {}; array set changes {}; array set seen {}
    # Resolve stable tracking identities before any operation can rename a net.
    foreach sink $sinks {
        require [expr {![info exists seen($sink)]}] "Duplicate rewired sink: $sink"
        set seen($sink) 1
        set key [tracking_key $sink]
        set objects [get_nets -of_objects [pin $sink]]
        require [expr {[llength $objects] == 1}] "Ambiguous rewired sink net: $sink"
        set old [get_property NAME $objects]
        if {![info exists groups($old)]} {lappend order $old}
        lappend groups($old) $sink
        if {$key ne ""} {
            if {![info exists changes($key)]} {lappend key_order $key}
            lappend changes($key) $sink
        }
    }
    foreach old $order {execopt::disconnect_segment $old $groups($old)}
    variable track
    foreach key $key_order {
        require [dict exists $track $key] "Missing original tracking entry: $key"
        dict set track $key removed [concat [dict get $track $key removed] $changes($key)]
    }
    set pairs {}; foreach sink $sinks {lappend pairs $newnet $sink}
    execopt::connect_many $pairs
}
proc sb::bind {name slr} {
    set c [cell $name]
    foreach pb [get_pblocks -quiet -of_objects $c] {remove_cells_from_pblock $pb $c}
    set pbname sbeco_$slr
    if {![llength [get_pblocks -quiet $pbname]]} {
        set pb [create_pblock $pbname]
        resize_pblock $pb -add $slr
        set_property IS_SOFT false $pb
        set_property EXCLUDE_PLACEMENT false $pb
    }
    add_cells_to_pblock [get_pblocks $pbname] $c
}
proc sb::capture_receivers {plan} {
    # Avoid repeated large-plan lookups in Vivado's Tcl interpreter. Keep the
    # original first-visit order and the exact saved fixed-cell mapping.
    array set sources {}
    foreach c [dict keys [dict get $plan data]] {set sources($c) 1}
    array set seen {}
    set receivers {}
    set visits 0
    dict for {c item} [dict get $plan data] {
        dict for {h v} [dict get $item helpers] {
            foreach p [dict get $v leaves] {
                incr visits
                set leaf [file dirname $p]
                if {![info exists seen($leaf)]} {
                    set seen($leaf) 1
                    lappend receivers $leaf
                }
            }
        }
    }
    puts "SBECO_PROGRESS [clock seconds] receiver_visits=$visits unique_receivers=[llength $receivers]"; flush stdout
    prefetch $receivers
    set fixed [dict get $plan fixed]
    foreach leaf $receivers {
        require [expr {![info exists sources($leaf)]}] "Broadcast source is also a frozen sink: $leaf"
        dict set fixed $leaf [position $leaf]
    }
    dict set plan fixed $fixed
    return $plan
}
proc sb::apply {plan out} {
    variable protect_cells
    variable protect_nets
    variable track
    spatial_cache
    reset_edit_state
    puts "SBECO_STEP [clock seconds] validate_plan"; flush stdout
    # Reject stale plans before any checkpoint mutation.
    dict for {c item} [dict get $plan data] {
        require [expr {[config $c] eq [dict get $item config]}] "Stale source configuration: $c"
        dict for {p v} [dict get $item inputs] {
            require [expr {[signal $c/$p] eq [dict get $v signal]}] "Stale source input: $c/$p"
        }
        set expected {}
        dict for {slr pins} [dict get $item groups] {lappend expected {*}$pins}
        require [expr {[loads $c/Q] eq [lsort $expected]}] "Stale source load set: $c"
    }
    dict for {name item} [dict get $plan ce] {
        set c [dict get $item original]
        require [expr {[config $c] eq [dict get $item config]}] "Stale CE configuration: $c"
        dict for {p v} [dict get $item inputs] {
            require [expr {[signal $c/$p] eq [dict get $v signal]}] "Stale CE input: $c/$p"
        }
        foreach p [dict get $item loads] {
            if {![string match sbeco_* $p]} {
                require [expr {[drivers $p] eq [list [dict get $item driver]]}] "Stale CE load: $p"
            }
        }
    }
    puts "SBECO_STEP [clock seconds] input_guard"; flush stdout
    if {[dict size [dict get $plan data]] && (![dict exists $plan selection] || [dict get $plan selection] eq "timing")} {
        set d_pins [get_pins -of_objects [get_cells [dict keys [dict get $plan data]]] -filter {REF_PIN_NAME == D}]
        set check [get_timing_paths -to $d_pins -delay_type max -max_paths 1]
        require [expr {[llength $check] == 1}] "Missing input timing for the selected broadcast registers"
        set margin [get_property SLACK $check]
        require [expr {$margin >= 1.0}] "Existing D input setup margin below 1 ns: $margin"
        dict set plan input_setup_guard_ns $margin
    }
    puts "SBECO_STEP [clock seconds] capture_fixed_receivers"; flush stdout
    set plan [capture_receivers $plan]
    dict set plan ce_endpoints {}
    puts "SBECO_STEP [clock seconds] capture_ce_endpoints"; flush stdout
    dict for {name item} [dict get $plan ce] {
        foreach p [dict get $item loads] {
            set c [file dirname $p]
            if {![string match sbeco_* $c] && ![dict exists $plan ce_endpoints $c]} {
                dict set plan ce_endpoints $c [dict create config [config $c] inputs [inputs $c] qloads [loads $c/Q]]
            }
        }
    }
    puts "SBECO_STEP [clock seconds] unlock_boundaries"; flush stdout
    set unroute {}
    set completed_roots 0
    dict for {c item} [dict get $plan data] {
        unlock_cell $c
        dict for {p value} [dict get $item inputs] {
            set constant [expr {[lindex [dict get $value signal] 0] eq "constant"}]
            unlock_net $c/$p [expr {$p ne "C" && !$constant}]
            if {$p ne "C" && !$constant} {lappend unroute {*}[names [get_nets -segments -of_objects [pin $c/$p]]]}
        }
        unlock_net $c/Q
        lappend unroute {*}[names [get_nets -segments -of_objects [pin $c/Q]]]
        dict for {h v} [dict get $item helpers] {unlock_cell $h}
        incr completed_roots
        if {$completed_roots % 16 == 0} {
            variable protected_net_seen
            puts "SBECO_PROGRESS [clock seconds] unlocked_roots=$completed_roots protected_segments=[array size protected_net_seen]"; flush stdout
        }
    }
    dict for {name item} [dict get $plan ce] {
        set c [dict get $item original]
        unlock_cell $c
        unlock_net $c/O
        lappend unroute {*}[names [get_nets -segments -of_objects [pin $c/O]]]
        dict for {p v} [dict get $item inputs] {
            set constant [expr {[lindex [dict get $v signal] 0] eq "constant"}]
            unlock_net $c/$p [expr {!$constant}]
            if {!$constant} {lappend unroute {*}[names [get_nets -segments -of_objects [pin $c/$p]]]}
        }
        foreach p [dict get $item loads] {
            set c [file dirname $p]
            if {![string match sbeco_* $c]} {unlock_cell $c}
        }
    }
    puts "SBECO_STEP [clock seconds] unroute_changed_nets"; flush stdout
    if {[llength $unroute]} {route_design -unroute -nets [get_nets [lsort -unique $unroute]]}
    puts "SBECO_STEP [clock seconds] copy_data_registers"; flush stdout
    dict for {c item} [dict get $plan data] {
        bind $c [dict get $item source_slr]
        dict for {slr replica} [dict get $item replicas] {
            create_cell -reference [dict get $item ref] $replica
            dict for {p v} [dict get $item config] {set_property $p $v [cell $replica]}
            dict for {p v} [dict get $item inputs] {connect_input $c/$p $replica/$p}
            create_net ${replica}_Q
            connect_net -net [get_nets ${replica}_Q] -objects [pin $replica/Q]
            rewire_many [dict get $item groups $slr] ${replica}_Q
            bind $replica $slr
        }
    }
    puts "SBECO_STEP [clock seconds] copy_local_ce"; flush stdout
    dict for {name item} [dict get $plan ce] {
        set original [dict get $item original]
        create_cell -reference [dict get $item ref] $name
        dict for {p v} [dict get $item config] {set_property $p $v [cell $name]}
        # Parallel copy of the existing truth table and its inputs; never old O -> new I.
        dict for {p v} [dict get $item inputs] {connect_input $original/$p $name/$p}
        create_net ${name}_O
        connect_net -net [get_nets ${name}_O] -objects [pin $name/O]
        rewire_many [dict get $item loads] ${name}_O
        bind $name [dict get $item target_slr]
    }
    puts "SBECO_STEP [clock seconds] restore_protection"; flush stdout
    # Group restoration by the original value; retain every original record.
    foreach kind {cell net} records [list $protect_cells $protect_nets] {
        array set restore_groups {}
        dict for {name v} $records {
            if {$kind eq "cell" && ![one_bit $v]} {continue}
            lappend restore_groups($v) $name
        }
        foreach v [array names restore_groups] {
            foreach batch [chunks $restore_groups($v) 256] {
                if {$kind eq "cell"} {set objects [get_cells $batch]} else {set objects [get_nets $batch]}
                require [expr {[llength $objects] == [llength $batch]}] "Missing protected object during restoration"
                if {$v eq ""} {reset_property DONT_TOUCH $objects} else {set_property DONT_TOUCH $v $objects}
            }
        }
        array unset restore_groups *
    }
    set roots [dict keys [dict get $plan data]]
    set added [names [get_cells -quiet sbeco_*]]
    set protected [concat $roots $added]
    if {[llength $protected]} {set_property DONT_TOUCH true [get_cells $protected]}
    foreach c $protected {
        set_property DONT_TOUCH true [get_nets -segments -of_objects [get_pins -of_objects [cell $c] -filter {DIRECTION == OUT}]]
    }
    set fixed [dict keys [dict get $plan fixed]]
    if {[llength $fixed]} {
        set_property IS_LOC_FIXED true [get_cells $fixed]
        set_property IS_BEL_FIXED true [get_cells $fixed]
    }
    # Existing CE endpoints keep their current SLR but are free to move within it.
    set ce_bound {}
    dict for {name item} [dict get $plan ce] {
        foreach p [dict get $item loads] {
            set c [file dirname $p]
            if {![string match sbeco_* $c]} {bind $c [dict get $item target_slr]}
            dict set ce_bound $c [dict get $item target_slr]
        }
    }
    dict set plan ce_bound $ce_bound
    dict set plan tracked $track
    dict set plan protection [dict create cells $protect_cells nets $protect_nets]
    set manifest [open $out/replicas.tsv w]
    puts $manifest "kind\toriginal\treplica\ttarget_slr\tloads"
    dict for {c item} [dict get $plan data] {
        dict for {slr replica} [dict get $item replicas] {
            puts $manifest "FF\t$c\t$replica\t$slr\t[llength [dict get $item groups $slr]]"
        }
    }
    dict for {name item} [dict get $plan ce] {
        puts $manifest "CE\t[dict get $item original]\t$name\t[dict get $item target_slr]\t[llength [dict get $item loads]]"
    }
    close $manifest
    save $plan $out/plan.tcl
    return $plan
}
proc sb::verify {plan out placed} {
    variable positions
    variable signal_cache
    set signal_cache {}
    spatial_cache
    if {$placed} {prefetch [dict keys [dict get $plan fixed]]}
    file mkdir $out
    set current [counts]
    set expected_lut_added [dict get $plan lut_added]
    if {[dict exists $plan regional_lut_added]} {incr expected_lut_added [dict get $plan regional_lut_added]}
    array set source_seen {}; foreach name [dict keys [dict get $plan data]] {set source_seen($name) 1}
    foreach kind {ff lut} {
        require [expr {[dict get $current $kind] == [dict get $plan counts_before $kind]+($kind eq "lut" ? $expected_lut_added : [dict get $plan ff_added])}] \
            "Unexpected $kind count change"
    }
    set ce_map {}
    dict for {name item} [dict get $plan ce] {
        require [expr {[config $name] eq [dict get $item config]}] "CE truth table changed: $name"
        dict for {p v} [dict get $item inputs] {
            require [expr {[signal $name/$p] eq [dict get $v signal]}] "CE input changed: $name/$p"
        }
        require [expr {[loads $name/O] eq [lsort [dict get $item loads]]}] "CE load set mismatch: $name"
        foreach p [dict get $item loads] {dict set ce_map $p $name/O}
        if {$placed} {require [expr {[dict get [position $name] slr] eq [dict get $item target_slr]}] "CE outside target SLR"}
    }
    set report [open $out/positions.tsv w]
    puts $report "kind\tcell\tslr\tloc\tbel\tfanout"
    dict for {c item} [dict get $plan data] {
        set all [dict create [dict get $item source_slr] $c]
        dict for {slr replica} [dict get $item replicas] {dict set all $slr $replica}
        dict for {slr ff} $all {
            require [expr {[config $ff] eq [dict get $item config]}] "FF config mismatch: $ff"
            dict for {p v} [dict get $item inputs] {
                set expected [dict get $v signal]
                if {[dict exists $ce_map $ff/$p]} {set expected [list drivers [list [dict get $ce_map $ff/$p]]]}
                require [expr {[signal $ff/$p] eq $expected}] "FF input changed: $ff/$p"
            }
            require [expr {[loads $ff/Q] eq [lsort [dict get $item groups $slr]]}] "Q group mismatch: $ff"
            if {$placed} {
                set pos [position $ff]
                require [expr {[dict get $pos slr] eq $slr}] "FF outside target SLR: $ff"
                puts $report "FF\t$ff\t$slr\t[dict get $pos loc]\t[dict get $pos bel]\t[llength [loads $ff/Q]]"
            }
        }
        dict for {h v} [dict get $item helpers] {
            require [expr {[config $h] eq [dict get $v config] && [loads $h/O] eq [dict get $v leaves]}] "Helper logic/leaf connection changed: $h"
            if {$placed} {require [expr {[position $h] eq [dict get $v position]}] "Data helper moved: $h"}
        }
    }
    dict for {name item} [dict get $plan ce] {
        if {$placed} {
            set pos [position $name]
            puts $report "CE\t$name\t[dict get $pos slr]\t[dict get $pos loc]\t[dict get $pos bel]\t[llength [loads $name/O]]"
        }
    }
    close $report
    dict for {c slr} [dict get $plan ce_bound] {
        if {$placed} {require [expr {[dict get [position $c] slr] eq $slr}] "CE endpoint moved to another SLR: $c"}
    }
    dict for {c v} [dict get $plan ce_endpoints] {
        require [expr {[config $c] eq [dict get $v config]}] "Existing CE endpoint FF configuration changed: $c"
        dict for {p value} [dict get $v inputs] {
            if {$p eq "CE"} {continue}
            require [expr {[signal $c/$p] eq [dict get $value signal]}] "Existing CE endpoint non-CE input changed: $c/$p"
        }
        if {![info exists source_seen($c)]} {
            require [expr {[loads $c/Q] eq [dict get $v qloads]}] "Existing CE endpoint Q changed: $c"
        }
    }
    if {$placed} {
        dict for {c pos} [dict get $plan fixed] {require [expr {[position $c] eq $pos}] "Fixed receiving cell moved: $c"}
    }
    set tracked_count 0
    set fanout [open $out/modified_nets.tsv w]
    puts $fanout "net\tloads_before\tloads_after\tover_99\tupstream_added\tremoved"
    dict for {net v} [dict get $plan tracked] {
        set expected {}
        foreach p [concat [dict get $v before] [dict get $v added]] {dict set expected $p 1}
        foreach p [dict get $v removed] {dict unset expected $p}
        # Some anchors are rewired sinks. Resolve the original net through surviving drivers.
        set n [get_nets -quiet [list $net]]
        require [expr {[llength $n] == 1}] "Original tracked net missing: $net"
        set observed [lsort -unique [names [get_pins -quiet -of_objects \
            [get_nets -segments -of_objects [get_pins -of_objects $n]] -filter {DIRECTION == IN && IS_LEAF == 1}]]]
        require [expr {$observed eq [lsort [dict keys $expected]]}] "Tracked net load mismatch: $net"
        puts $fanout "$net\t[llength [dict get $v before]]\t[llength $observed]\t[expr {[llength $observed]>99}]\t[llength [dict get $v added]]\t[llength [dict get $v removed]]"
        incr tracked_count
    }
    close $fanout
    set f [open $out/structural_pass.txt w]
    puts $f "PASS: FF+[dict get $plan ff_added], LUT+[dict get $plan lut_added], tracked_nets=$tracked_count; exact FF inputs/config, parallel CE truth tables, data helper leaves, SLR groups. placed=$placed"
    close $f
}
proc sb::reports {plan out final} {
    file mkdir $out
    report_timing_summary -delay_type min_max -file $out/timing_summary.rpt
    set ff [dict keys [dict get $plan data]]
    set cepins {}
    dict for {c item} [dict get $plan data] {
        dict for {slr name} [dict get $item replicas] {
            if {[llength [get_cells -quiet $name]]} {lappend ff $name}
        }
    }
    if {[llength $ff]} {
        set objects [get_cells $ff]
        report_timing -from $objects -delay_type max -max_paths 100 -nworst 100 -unique_pins -file $out/data_broadcast.rpt
        set endpoint_limit [llength $ff]
        report_timing -to [get_pins -of_objects $objects -filter {REF_PIN_NAME == D}] -delay_type max -max_paths $endpoint_limit -nworst 1 -file $out/data_input.rpt
        report_timing -to [get_pins -of_objects $objects -filter {REF_PIN_NAME == CE}] -delay_type max -max_paths $endpoint_limit -nworst 1 -file $out/data_enable.rpt
        report_timing -to [get_pins -of_objects $objects -filter {REF_PIN_NAME == D}] -delay_type min -max_paths $endpoint_limit -nworst 1 -file $out/data_input_hold.rpt
        report_timing -to [get_pins -of_objects $objects -filter {REF_PIN_NAME == CE}] -delay_type min -max_paths $endpoint_limit -nworst 1 -file $out/data_enable_hold.rpt
    }
    dict for {name item} [dict get $plan ce] {
        foreach p [dict get $item loads] {
            if {[llength [get_pins -quiet [list $p]]]} {lappend cepins $p}
        }
    }
    if {[llength $cepins]} {
        report_timing -to [get_pins [lsort -unique $cepins]] -delay_type max -max_paths 256 -nworst 1 -file $out/local_ce.rpt
    }
    set existing {}
    foreach p $cepins {if {![string match sbeco_* $p]} {lappend existing $p}}
    if {[llength $existing]} {
        report_timing -to [get_pins [lsort -unique $existing]] -delay_type max -max_paths 256 -nworst 1 -file $out/existing_ce.rpt
    }
    if {$final} {
        report_timing -delay_type max -max_paths 1000 -nworst 1000 -unique_pins -file $out/worst1000.rpt
        report_route_status -file $out/route_status.rpt
        report_utilization -file $out/utilization.rpt
        report_utilization -slr -file $out/utilization_slr.rpt
        report_drc -file $out/drc.rpt
    }
}
