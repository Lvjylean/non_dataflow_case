# Immutable structural inventory, bounded joint planning, then one exact ECO.
source [file join [file dirname [info script]] locality_inventory.tcl]
source [file join [file dirname [info script]] static_discovery_cache.tcl]
source [file join [file dirname [info script]] input_progress.tcl]
namespace eval bl {variable module_dir [file dirname [info script]]}
proc bl::canonical_graph {graph} {
    # Python emits valid Tcl lists using quoted elements. Existing native guards
    # compare canonical list strings, so normalize without losing duplicates.
    dict for {key pins} [dict get $graph expected] {
        set unique [lsort -unique $pins]
        if {[llength $unique]!=[llength $pins]} {error "duplicate_planned_sink:$key"}
        dict set graph expected $key $unique
    }
    return $graph
}
proc bl::finite {value} {
    if {![string is double -strict $value]} {return 0}
    if {[catch {expr {abs(double($value))<1.0e20}} ok]} {return 0}
    return $ok
}
proc bl::timing_contract {key targets} {
    # UG912 TIMING_PATH documents STARTPOINT_CLOCK, ENDPOINT_CLOCK, EXCEPTION,
    # REQUIREMENT and SLACK.  UG835 2023.2 documents -user_ignored.  A single
    # worst path cannot certify other data/select branches: exhaust a bounded
    # path collection, or reject when the collection reaches its limit.
    # https://docs.amd.com/r/2022.1-English/ug912-vivado-properties/TIMING_PATH
    # https://docs.amd.com/r/2023.2-English/ug835-vivado-tcl-commands/get_timing_paths
    if {![llength $targets]} {error missing_cone_targets}
    set endpoint_names {}
    foreach target $targets {
        set pin [sb::pin $target];set cell [sb::cell [file dirname $target]]
        set ref [get_property REF_NAME $cell]
        if {[regexp {^(FDRE|FDSE|RAMB(18|36)E[12]|URAM288(_BASE)?)$} $ref]} {
            lappend endpoint_names $target
        } else {
            foreach endpoint [all_fanout -flat -endpoints_only -trace_arcs all -from $pin] {
                if {[get_property CLASS $endpoint] ne "pin"} {error unsupported_cone_port_endpoint}
                lappend endpoint_names [get_property NAME $endpoint]
            }
        }
    }
    set endpoint_names [lsort -unique $endpoint_names]
    if {![llength $endpoint_names]} {error missing_cone_endpoints}
    if {[llength $endpoint_names]>256} {error cone_timing_endpoint_budget}
    set endpoints [get_pins $endpoint_names]
    if {[lsort [sb::names $endpoints]] ne $endpoint_names} {error missing_cone_endpoint_objects}
    set through [sb::pin $key]
    # Include false paths/clock-group exclusions explicitly; they otherwise do
    # not appear among ordinary setup/hold paths, regardless of -max_paths.
    if {[llength [get_timing_paths -through $through -to $endpoints -user_ignored -max_paths 1 -nworst 1]]} {
        error unsupported_user_ignored_cone_path
    }
    set clock_name "";set period "";set worst "";set requirement ""
    foreach type {max min} {
        set paths [get_timing_paths -through $through -to $endpoints -delay_type $type -max_paths 513 -nworst 513]
        if {![llength $paths]} {error missing_cone_${type}_paths}
        if {[llength $paths]>=513} {error cone_timing_path_budget}
        set covered {}
        foreach path $paths {
            set exception [string trim [get_property EXCEPTION $path]]
            if {$exception ne ""} {error "unsupported_cone_exception:$exception"}
            set start [get_property STARTPOINT_CLOCK $path]
            set end [get_property ENDPOINT_CLOCK $path]
            if {$start eq "" || $end eq "" || $start ne $end} {error unsupported_cone_clock_pair}
            set clocks [get_clocks [list $start]]
            if {[llength $clocks]!=1} {error ambiguous_cone_clock}
            set p [get_property PERIOD $clocks]
            set req [get_property REQUIREMENT $path];set slack [get_property SLACK $path]
            if {![finite $p] || $p<=0 || ![finite $req] || ![finite $slack]} {error nonfinite_cone_timing}
            set expected [expr {$type eq "max" ? $p : 0.0}]
            if {abs($req-$expected)>1e-5} {error unsupported_cone_timing_requirement}
            if {$clock_name ne "" && ($start ne $clock_name || abs($p-$period)>1e-5)} {error multiple_cone_clocks}
            set clock_name $start;set period $p
            if {$type eq "max" && ($worst eq "" || $slack<$worst)} {set worst $slack;set requirement $req}
            lappend covered [get_property ENDPOINT_PIN $path]
        }
        # An untimed/disabled endpoint is not silently removed from the proof.
        if {[lsort -unique $covered] ne $endpoint_names} {error incomplete_cone_${type}_endpoint_coverage}
    }
    return [list $worst $requirement $period $clock_name $clock_name supported]
}
proc bl::through_slacks {keys targets_by_root path {bad_roots {}}} {
    set f [open $path w];puts $f "key\tmax\trequirement\tperiod\tstart_clock\tend_clock\tstatus"
    foreach key $keys {
        set result {}
        if {[dict exists $bad_roots $key]} {
            set why [dict get $bad_roots $key]
        } elseif {[catch {
            if {![dict exists $targets_by_root $key]} {error missing_cone_targets}
            set result [timing_contract $key [dict get $targets_by_root $key]]
        } why]} {
            set why [string map [list \t { } \n { } \r { }] $why]
        }
        if {![llength $result]} {set result [list "" "" "" "" "" $why]}
        puts $f [join [linsert $result 0 $key] \t]
    }
    close $f
}
proc bl::discover {out min_fanout} {
    variable module_dir
    sb::require [expr {![llength [get_cells -quiet sbeco_local_*]]}] "Locality copies already exist"
    set folder $out/locality;file mkdir $folder
    lb::log "locality_inventory_begin"
    # Capture, host preparation and native candidate readback share one epoch.
    # Any mutation/reopen invalidates the context before a snapshot can be read.
    set code [catch {vs::with locality_candidate_reads [list bl::discover_readonly $out $min_fanout $folder]} result options]
    jip::end [expr {$code ? "ERROR" : "COMPLETE"}]
    locality_inventory::deactivate
    locality_inventory::connection_save $folder/candidate_input_reuse.tsv
    if {[info exists ::vs::last_statistics]} {vs::save $::vs::last_statistics $folder/native_read_reuse.tsv}
    if {$code} {return -options $options $result}
    return $result
}
proc bl::discover_readonly {out min_fanout folder} {
    variable module_dir
    set fresh_inventory 0
    if {![bl_static_cache::prepare $folder]} {
        locality_inventory::capture $folder
        set fresh_inventory 1
        puts [exec python3 $module_dir/locality_plan.py prepare $folder]
        bl_static_cache::publish $folder
    }
    # Only the just-captured, unchanged live database supplies this metadata.
    # Reopened static files never authorize an older in-memory physical view.
    return [bl::discover_inputs $out $min_fanout $folder $fresh_inventory]
}
proc bl::discover_inputs {out min_fanout folder fresh_inventory} {
    variable module_dir
    locality_inventory::connection_reset
    jip::begin $out
    if {$fresh_inventory} {
        locality_inventory::activate
        locality_inventory::connection_load $folder
    }
    source $folder/requests.tcl
    set ::jip::total [dict size $bl_requests]
    jip::phase candidate_inputs
    foreach var {cells inputs nodes nets} {array unset ::ji::$var *}
    set cf [open $out/ji_candidates.tsv w]
    puts $cf "id\tkey\treplica\tref\ttarget\tx\ty\tloads\tdriver\tdriver_cell\tstatus"
    set cones [open $out/ji_cones.tsv w];puts $cones "key\tcell"
    set endpoints {};set expanded {}
    dict for {id item} $bl_requests {
        set candidate_tick [clock microseconds]
        set key [dict get $item key];set name [file dirname $key]
        set ref [dict get [ji::describe $name] ref];set status supported;set seen {};set active {};set driver ""
        if {[catch {
            ji::record $name
            set ds [dict get $::ji::inputs($name) D]
            if {[dict get $ds kind] ne "ordinary" || [lindex [dict get $ds signal] 0] ne "drivers"} {error unsupported_D_boundary}
            set driver [dict get $ds key]
            if {[dict exists $expanded $name]} {set seen [dict get $expanded $name]} \
            else {ji::expand [file dirname $driver] 0 seen active;dict set expanded $name $seen}
            dict for {pin sig} $::ji::inputs($name) {if {$pin in {D CE R S}} {lappend endpoints $name/$pin}}
        } why]} {set status $why}
        foreach c [dict keys $seen] {puts $cones "$key\t$c";lappend bl_templates $c}
        # Native positions are only ever read for existing cells.
        foreach pin [dict get $item terminals] {
            if {[catch {ji::describe [file dirname $pin]} why]} {set status "terminal_position:$why"}
        }
        puts $cf [join [list $id $key [dict get $item replica] $ref [dict get $item target] \
            [dict get $item x] [dict get $item y] 0 $driver [file dirname $driver] $status] \t]
        flush $cf;flush $cones
        jip::candidate $id $candidate_tick [dict size $seen] $status
    }
    close $cf;close $cones
    jip::phase template_records
    if {[info exists bl_control_aliases]} {lappend bl_templates {*}$bl_control_aliases}
    set tf [open $folder/template_status.tsv w];puts $tf "cell\tstatus"
    foreach name [lsort -unique $bl_templates] {
        if {[catch {ji::record $name} why]} {puts $tf "$name\t$why"} else {puts $tf "$name\tsupported"}
        jip::checkpoint
    };close $tf
    # Do not let a missing/unsupported shared receiver abort unrelated proposals.
    # Reject the affected root through its timing-status row instead.
    jip::phase cone_receivers
    set bad_roots {}
    foreach key $bl_cone_roots {
        if {[catch {
            foreach sink [ji::loads $key] {ji::describe [file dirname $sink]}
        } why]} {dict set bad_roots $key "cone_receiver_position:[string map [list \t { } \n { } \r { }] $why]"}
    }
    jip::phase endpoint_sta
    ji::slacks [lsort -unique $endpoints] $out/ji_slacks.tsv
    if {![info exists bl_cone_targets]} {set bl_cone_targets {}}
    jip::phase through_sta
    bl::through_slacks $bl_cone_roots $bl_cone_targets $folder/through_slacks.tsv $bad_roots
    jip::phase serialization
    set f [open $out/ji_cells.tsv w];puts $f "name\tref\tslr\tx\ty\tperiod"
    foreach name [array names ::ji::cells] {
        set row {};foreach k {name ref slr x y period} {lappend row [dict get $::ji::cells($name) $k]}
        puts $f [join $row \t]
    };close $f
    set f [open $out/ji_edges.tsv w];puts $f "cell\tpin\tkey\tkind\tsource_cell"
    foreach name [array names ::ji::inputs] {
        dict for {pin sig} $::ji::inputs($name) {
            set source "";if {[dict get $sig kind] eq "ordinary" && [lindex [dict get $sig signal] 0] eq "drivers"} {set source [file dirname [dict get $sig key]]}
            puts $f [join [list $name $pin [dict get $sig key] [dict get $sig kind] $source] \t]
        }
    };close $f
    set f [open $out/ji_nets.tsv w];puts $f "key\tfanout"
    foreach key [array names ::ji::nets] {if {[dict get $::ji::nets($key) kind] eq "ordinary"} {puts $f "$key\t[llength [dict get $::ji::nets($key) before]]"}};close $f
    report_utilization -slr -file $out/ji_utilization_slr.rpt
    set f [open $out/ji_capacity.tsv w];puts $f "slr\tkind\tcapacity"
    foreach slr [get_slrs] {
        set n [llength [get_sites -of_objects $slr -filter {SITE_TYPE == SLICEL || SITE_TYPE == SLICEM}]]
        foreach kind {LUT FF MUXF7 MUXF8 MUXF9} factor {8 16 4 2 1} {puts $f "[get_property NAME $slr]\t$kind\t[expr {$n*$factor}]"}
    };close $f
    set args [list python3 $module_dir/locality_plan.py finish $folder]
    foreach envname {JI_MARGIN JI_MAX_ADDED} option {--margin --max-added} {
        if {[info exists ::env($envname)]} {lappend args $option $::env($envname)}
    }
    if {[info exists ::env(JI_EXCLUDE)] && $::env(JI_EXCLUDE) ne ""} {lappend args --exclude $::env(JI_EXCLUDE)}
    jip::phase host_plan
    puts [exec {*}$args];source $folder/final_plan.tcl
    jip::phase plan_readback
    set bl_graph [bl::canonical_graph $bl_graph]
    set roots {};set nets {};set pin_slrs {}
    foreach name $bl_roots {
        ji::record $name
        set node $::ji::nodes($name);set key "$name/[dict get $node pin]"
        dict set roots $key $node
        lappend bl_keys $key
        dict for {pin sig} [dict get $node inputs] {lappend bl_keys [dict get $sig key]}
    }
    foreach key [dict values [dict get $bl_graph new_inputs]] {
        if {![dict exists $bl_graph replicas [file dirname $key]]} {lappend bl_keys $key}
    }
    foreach key [lsort -unique $bl_keys] {
        if {![info exists ::ji::nets($key)]} {
            set sig [ji::signal $key]
            set before {};if {[dict get $sig kind] eq "ordinary"} {set before [ji::loads [dict get $sig anchor]]}
            set ::ji::nets($key) [dict merge $sig [dict create before $before]]
        }
        dict set nets $key $::ji::nets($key)
    }
    set local [dict create schema slr-local-functional-v1 snapshot [dict create roots $roots nets $nets pin_slrs $pin_slrs] \
        copies $bl_copies graph $bl_graph decisions {} \
        joint_input [dict create schema joint-input-locality-v1 accepted $bl_keep aux $bl_aux hints $bl_hints]]
    if {[info exists bl_reused]} {dict set local reused_positions $bl_reused}
    set plan [lb::planned_plan $local $min_fanout]
    dict set plan locality_schema broadcast-locality-v1
    return $plan
}
