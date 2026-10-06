source [file join [file dirname [info script]] local_policy.tcl]
source [file join [file dirname [info script]] joint_input.tcl]
if {[info exists ::env(BL_LOCALITY)] && $::env(BL_LOCALITY) eq "1"} {source [file join [file dirname [info script]] locality_physical.tcl]}
namespace eval lb {variable module_dir [file dirname [info script]]; variable pblocks; variable pin_slrs; array set pin_slrs {}}
proc lb::log {s} {puts "LOCAL_BROADCAST [clock seconds] $s"; flush stdout}
proc lb::pin_slr {pin} {
    variable pin_slrs
    if {![info exists pin_slrs($pin)]} {set pin_slrs($pin) [dict get [sb::position [file dirname $pin]] slr]}
    return $pin_slrs($pin)
}
proc lb::describe_signal {pin} {
    set signal [sb::signal $pin]; set type [lindex $signal 0]
    if {$type in {constant clock}} {return [dict create key $signal kind $type anchor $pin slr "" signal $signal]}
    if {[llength [get_clocks -quiet -of_objects [get_nets -of_objects [sb::pin $pin]]]]} {error "clock_used_as_data:$pin"}
    if {$type eq "drivers" && [llength [lindex $signal 1]] == 1} {
        set driver [lindex [lindex $signal 1] 0]
        if {[rf::known_protected_ip $driver]} {error "protected_input_source:$driver"}
        if {![input_source [sb::ref [file dirname $driver]] [file tail $driver]]} {error "unsupported_input_source:$driver"}
        return [dict create key $driver kind ordinary anchor $driver slr [pin_slr $driver] signal $signal]
    }
    if {$type eq "ports" && [llength [lindex $signal 1]] == 1} {
        return [dict create key $signal kind ordinary anchor $pin slr "" signal $signal]
    }
    error "ambiguous_input_source:$pin"
}
proc lb::record_net {arrayvar ordervar sig} {
    upvar 1 $arrayvar nets $ordervar order
    set key [dict get $sig key]
    if {[info exists nets($key)]} {return}
    set before {}
    if {[dict get $sig kind] eq "ordinary"} {set before [sb::loads [dict get $sig anchor]]}
    set nets($key) [dict merge $sig [dict create before $before]]
    lappend order $key
}
proc lb::host_plan {snapshot out min_fanout} {
    variable module_dir
    set executable [auto_execok tclsh]
    sb::require [expr {[llength $executable]>0}] "System tclsh is required for isolated pure graph planning"
    set input [file join $out local_snapshot.tcl]
    set result [file join $out local_graph.tcl]
    set f [open ${input}.tmp w]
    puts $f {set lb_snapshot {}}
    dict for {key value} $snapshot {puts $f [list dict set lb_snapshot $key $value]}
    close $f; file rename -force ${input}.tmp $input
    log "host_plan_begin snapshot_bytes=[file size $input]"
    set message [exec {*}$executable [file join $module_dir local_planner.tcl] $input $result $min_fanout 2>@1]
    puts $message; flush stdout
    source $result
    sb::require [expr {[dict get $lb_local schema] eq "slr-local-functional-v1"}] "Unexpected host planner schema"
    log "host_plan_complete graph_bytes=[file size $result]"
    return $lb_local
}
proc lb::discover {out min_fanout} {
    if {[info exists ::env(BL_LOCALITY)] && $::env(BL_LOCALITY) eq "1"} {
        uplevel #0 [list source [file join $::lb::module_dir locality_backend.tcl]]
        return [bl::discover $out $min_fanout]
    }
    variable pin_slrs; array unset pin_slrs *
    sb::spatial_cache
    sb::require [expr {![llength [get_cells -quiet sbeco_local_*]]}] "Local replicas already exist"
    array set roots_data {}; array set nets_data {}; array set sink_slrs {}
    set root_order {}; set net_order {}
    set f [open $out/local_discovery.tsv w]
    puts $f "driver\tref\tfanout\tstatus"
    set nets [get_nets -hier -quiet -filter "FLAT_PIN_COUNT > $min_fanout && TYPE != POWER && TYPE != GROUND"]
    set roots [lsort -unique [sb::names [get_nets -quiet -segments -top_net_of_hierarchical_group $nets]]]
    unset nets
    set count 0
    foreach net $roots {
        incr count
        if {$count % 256 == 1} {log "discover=$count/[llength $roots]"; flush $f}
        set n [get_nets -quiet [list $net]]
        if {[llength [get_clocks -quiet -of_objects $n]]} {continue}
        set segments [get_nets -quiet -segments $n]
        set drivers [sb::names [get_pins -quiet -of_objects $segments -filter {IS_LEAF == 1 && DIRECTION == OUT}]]
        if {[llength $drivers] != 1 || [llength [get_ports -quiet -of_objects $segments]]} {continue}
        set driver [lindex $drivers 0]; set cell [file dirname $driver]; set ref [sb::ref $cell]
        if {[output_pin $ref] eq "" || [output_pin $ref] ne [file tail $driver]} {continue}
        set why ""; set sinks [sb::loads $driver]
        if {[llength $sinks] < $min_fanout} {continue}
        if {[rf::known_protected_ip $driver]} {set why protected_ip} \
        elseif {[rf::protected_ancestor $cell] ne ""} {set why protected_hierarchy} \
        elseif {[rf::asynchronous $cell]} {set why asynchronous_register} \
        elseif {[sb::one_bit [get_property IS_ROUTE_FIXED $n]] || [rf::has_fixed_route [get_property FIXED_ROUTE $n]]} {set why fixed_route}
        if {$why eq ""} {
            foreach sink $sinks {
                set sc [file dirname $sink]
                if {[rf::known_protected_ip $sink] || [rf::protected_ancestor $sc] ne ""} {set why protected_sink; break}
                if {![ordinary_input [sb::ref $sc] [file tail $sink]]} {set why unsupported_sink; break}
                if {[rf::asynchronous $sc]} {set why asynchronous_sink; break}
            }
        }
        set inputs {}
        if {$why eq ""} {
            foreach ip [sb::names [get_pins -quiet -of_objects [sb::cell $cell] -filter {IS_LEAF == 1 && DIRECTION == IN}]] {
                if {[catch {describe_signal $ip} sig]} {set why $sig; break}
                dict set inputs [file tail $ip] $sig
            }
        }
        if {$why ne ""} {puts $f "$driver\t$ref\t[llength $sinks]\t$why"; continue}
        set slr [pin_slr $driver]
        foreach sink $sinks {set sink_slrs($sink) [pin_slr $sink]}
        lappend root_order $driver
        set roots_data($driver) [dict create cell $cell ref $ref pin [file tail $driver] slr $slr inputs $inputs config [sb::config $cell]]
        set sig [dict create key $driver kind ordinary anchor $driver slr $slr signal [list drivers [list $driver]]]
        record_net nets_data net_order $sig
        dict for {ip sig} $inputs {record_net nets_data net_order $sig}
        puts $f "$driver\t$ref\t[llength $sinks]\tstructurally_supported"
    }
    close $f
    set ordered_roots {}; foreach key $root_order {lappend ordered_roots $key $roots_data($key)}
    set ordered_nets {}; foreach key $net_order {lappend ordered_nets $key $nets_data($key)}
    set snapshot [dict create roots $ordered_roots nets $ordered_nets pin_slrs [array get sink_slrs]]
    log "planning_roots=[llength $root_order]"
    set local [host_plan $snapshot $out $min_fanout]
    set local [ji::enrich $local $out]
    set snapshot [dict get $local snapshot]
    set ff 0; set lut 0
    dict for {name item} [dict get $local graph replicas] {
        set ref [dict get $snapshot roots [dict get $item key] ref]
        if {$ref in {FDRE FDSE}} {incr ff} elseif {[regexp {^LUT} $ref]} {incr lut}
    }
    set plan [dict create schema slr-local-backend-v1 counts_before [sb::counts] path_limit 0 min_fanout $min_fanout \
        selection structure data {} ce {} fixed {} ff_added $ff lut_added $lut sampled_paths 0 \
        no_op [expr {$ff+$lut==0}] local_broadcast $local]
    set f [open $out/local_candidates.tsv w]; puts $f "driver_or_target\tdecision"
    dict for {key why} [dict get $local decisions] {puts $f "$key\t$why"}; close $f
    log "planned_ff=$ff planned_lut=$lut"
    return $plan
}
proc lb::source_net {local key} {
    if {[dict exists $local snapshot nets $key]} {
        set net [dict get $local snapshot nets $key]
        if {[dict get $net kind] eq "ordinary" && [lindex [dict get $net signal] 0] eq "drivers"} {
            return [get_nets -of_objects [sb::pin $key]]
        }
        return [get_nets -of_objects [sb::pin [dict get $net anchor]]]
    }
    return [get_nets -of_objects [sb::pin $key]]
}
proc lb::pblock_member_names {pb name cache_var} {
    upvar 1 $cache_var members
    if {![info exists members($name)]} {
        # Keep the complete membership, including hierarchical members. The
        # caller owns this cache; it must never survive a verification call.
        set members($name) [sb::names [get_cells -quiet -of_objects $pb]]
    }
    return $members($name)
}
proc lb::pblock_snapshot {{membership_cache_var ""}} {
    if {$membership_cache_var eq ""} {
        array set membership_cache {}
    } else {
        upvar 1 $membership_cache_var membership_cache
    }
    set result {}
    foreach pb [get_pblocks -quiet *] {
        set name [get_property NAME $pb]
        lappend result $name [dict create ranges [lsort [get_property GRID_RANGES $pb]] soft [get_property IS_SOFT $pb] \
            members [lsort [pblock_member_names $pb $name membership_cache]]]
    }
    return $result
}
proc lb::bind {name slr} {
    set pbname localrep_$slr
    set pb [get_pblocks -quiet $pbname]
    if {![llength $pb]} {
        set pb [create_pblock $pbname]
        resize_pblock $pb -add $slr
        set_property EXCLUDE_PLACEMENT false $pb
    }
    add_cells_to_pblock $pb [sb::cell $name]
    # Apply and read the hard-region property after all membership operations.
    set_property IS_SOFT false $pb
    sb::require [expr {![sb::one_bit [get_property IS_SOFT $pb]]}] "Unable to bind local replica to $slr"
}
proc lb::unlock_boundaries {local} {
    set snapshot [dict get $local snapshot]; set graph [dict get $local graph]
    array set cells {}; array set nets {}; array set touched {}; array set unroute {}
    set moved_pins {}
    dict for {sink route} [dict get $graph moves] {
        set cells([file dirname $sink]) 1
        lappend moved_pins $sink
        # A reused identity subtree can be moved without its old driver being
        # a replica template. Both real old and existing new sources matter.
        foreach key $route {
            if {![dict exists $graph replicas [file dirname $key]]} {set touched($key) 1}
        }
    }
    dict for {sink key} [dict get $graph new_inputs] {
        if {![dict exists $graph replicas [file dirname $key]]} {set touched($key) 1}
    }
    dict for {name item} [dict get $graph replicas] {
        set key [dict get $item key]; set touched($key) 1
        dict for {pin sig} [dict get $snapshot roots $key inputs] {set touched([dict get $sig key]) 1}
    }
    foreach key [array names touched] {
        sb::require [dict exists $snapshot nets $key] "Missing existing edit-boundary source: $key"
        set net [dict get $snapshot nets $key]
        if {[dict get $net kind] eq "ordinary"} {
            set objects [get_nets -quiet -segments [source_net $local $key]]
            if {[lindex [dict get $net signal] 0] eq "drivers"} {set cells([file dirname $key]) 1}
            foreach name [sb::names $objects] {set unroute($name) 1}
        } else {
            # Clock/supply inputs only need the anchor segment for new pins.
            # Expanding their global aliases would unlock unrelated design.
            set objects [get_nets -of_objects [sb::pin [dict get $net anchor]]]
        }
        foreach name [sb::names $objects] {set nets($name) 1}
    }
    # Query the live sink side too: its native hierarchical segment can differ
    # from the driver's segment and must be unlocked for disconnect_net.
    foreach batch [sb::chunks $moved_pins 512] {
        set objects [get_nets -quiet -segments -of_objects [execopt::exact_objects pin $batch]]
        foreach name [sb::names $objects] {set nets($name) 1;set unroute($name) 1}
    }
    # Snapshot signal kinds are not sufficient authority to unroute a clock
    # or a supply. Check native types as well, in batches for ordinary data.
    foreach batch [sb::chunks [array names unroute] 512] {
        set objects [execopt::exact_objects net $batch]
        set has_clocks [llength [get_clocks -quiet -of_objects $objects]]
        foreach name [sb::names $objects] object $objects type [sb::values TYPE $objects] {
            if {$type in {POWER GROUND} || ($has_clocks && [llength [get_clocks -quiet -of_objects $object]])} {
                unset unroute($name)
            }
        }
    }
    # Discover each ancestor once; keep the same protection contract as sb::unlock_cell.
    foreach cell [array names cells] {
        set parent [file dirname $cell]
        while {$parent ni {. / {}}} {
            if {[info exists cells($parent)]} {break}
            set cells($parent) 1; set parent [file dirname $parent]
        }
    }
    # Capture every original value before modifying any object, so a failed
    # native property write can restore the full, bounded protection set.
    set saved {};set changes {}
    foreach kind {cell net} names [list [array names cells] [array names nets]] {
        array set properties {}; set change {}
        foreach batch [sb::chunks $names 512] {
            set objects [execopt::exact_objects $kind $batch]
            foreach name [sb::names $objects] value [sb::values DONT_TOUCH $objects] {
                set properties($name) $value
                if {[sb::one_bit $value]} {lappend change $name}
            }
        }
        dict set saved $kind [array get properties]
        dict set changes $kind $change
        array unset properties *
    }
    set code [catch {
        dict for {kind change} $changes {
            foreach batch [sb::chunks $change 512] {set_property DONT_TOUCH false [execopt::exact_objects $kind $batch]}
        }
        dict for {kind records} $saved {
            foreach batch [sb::chunks [dict keys $records] 512] {
                set objects [execopt::exact_objects $kind $batch]
                foreach name [sb::names $objects] value [sb::values DONT_TOUCH $objects] {
                    sb::require [expr {![sb::one_bit $value]}] "Edit boundary remains DONT_TOUCH after unlock: $kind $name"
                }
            }
        }
    } result options]
    if {$code} {
        if {[catch {restore_boundaries $saved} restore_error]} {append result "\nProtection restoration also failed: $restore_error"}
        return -options $options $result
    }
    log "unlocked_cells=[array size cells] nets=[array size nets]"
    return [dict create properties $saved unroute [array names unroute]]
}
proc lb::restore_boundaries {properties} {
    dict for {kind records} $properties {
        array set groups {}
        dict for {name value} $records {lappend groups($value) $name}
        foreach value [array names groups] {
            foreach batch [sb::chunks $groups($value) 512] {
                set objects [execopt::exact_objects $kind $batch]
                if {$value eq ""} {reset_property DONT_TOUCH $objects} else {set_property DONT_TOUCH $value $objects}
            }
        }
        array unset groups *
    }
    dict for {kind records} $properties {
        foreach batch [sb::chunks [dict keys $records] 512] {
            set objects [execopt::exact_objects $kind $batch]
            foreach name [sb::names $objects] value [sb::values DONT_TOUCH $objects] {
                set expected [dict get $records $name]
                if {$expected eq ""} {set same [expr {$value eq ""}]} else {set same [expr {$value ne "" && [sb::one_bit $value] == [sb::one_bit $expected]}]}
                sb::require $same "Edit boundary DONT_TOUCH restoration failed: $kind $name expected=$expected actual=$value"
            }
        }
    }
}
proc lb::require_disconnected {pins} {
    foreach batch [sb::chunks [lsort -unique $pins] 512] {
        set objects [execopt::exact_objects pin $batch]
        set attached [get_nets -quiet -of_objects $objects]
        if {![llength $attached]} {continue}
        # Per-pin diagnostics run only on failure; do not reconnect any pins
        # when disconnect_net issued a warning but left a connection in place.
        foreach pin $batch {
            set net [get_nets -quiet -of_objects [execopt::exact_objects pin [list $pin]]]
            if {[llength $net]} {error "Disconnect did not release edit pin: $pin remains on [sb::names $net]"}
        }
        error "Disconnect batch still has attached nets: [sb::names $attached]"
    }
}
proc lb::planned_plan {local min_fanout} {
    set ff 0; set lut 0
    dict for {name item} [dict get $local graph replicas] {
        set ref [dict get $local snapshot roots [dict get $item key] ref]
        if {$ref in {FDRE FDSE}} {incr ff} elseif {[regexp {^LUT} $ref]} {incr lut}
    }
    return [dict create schema slr-local-backend-v1 counts_before [sb::counts] path_limit 0 min_fanout $min_fanout \
        selection structure data {} ce {} fixed {} ff_added $ff lut_added $lut sampled_paths 0 \
        no_op [expr {$ff+$lut==0}] local_broadcast $local]
}
proc lb::apply {plan out} {
    set local [dict get $plan local_broadcast]; set snapshot [dict get $local snapshot]; set graph [dict get $local graph]
    sb::spatial_cache; sb::reset_edit_state
    log "apply_capture_floorplan"
    dict set local original_pblocks [pblock_snapshot]
    log "apply_validate_boundaries"
    # Check the complete live boundary before any edit, including inputs shared by candidates.
    dict for {key net} [dict get $snapshot nets] {
        if {[dict get $net kind] eq "ordinary"} {sb::require [expr {[sb::loads [dict get $net anchor]] eq [dict get $net before]}] "Stale local boundary: $key"}
    }
    dict for {key root} [dict get $snapshot roots] {
        sb::require [expr {[sb::config [dict get $root cell]] eq [dict get $root config]}] "Stale local primitive: $key"
    }
    log "apply_unlock_boundaries"
    set boundary [unlock_boundaries $local]
    set code [catch {
    set unroute [dict get $boundary unroute]
    if {[llength $unroute]} {route_design -unroute -nets [get_nets [lsort -unique $unroute]]}
    log "create_replicas=[dict size [dict get $graph replicas]]"
    # Create all outputs first so dependent FF/LUT copies can be wired jointly.
    dict for {name item} [dict get $graph replicas] {
        set root [dict get $snapshot roots [dict get $item key]]
        create_cell -reference [dict get $root ref] $name
        dict for {p value} [dict get $root config] {set_property $p $value [sb::cell $name]}
        create_net ${name}_out
        connect_net -net [get_nets ${name}_out] -objects [sb::pin "$name/[dict get $root pin]"]
        # Only new cells enter whole-SLR hard Pblocks. Original floorplan is untouched.
        bind $name [dict get $item slr]
    }
    log "apply_prepare_connections"
    if {[dict exists $local joint_input]} {set local [ji::hint_constraints $local]}
    array set disconnects {}; array set resolved {}; set links {}
    dict for {sink route} [dict get $graph moves] {
        lassign $route old target
        set oldnet [sb::net_at $sink]
        lappend disconnects($oldnet) $sink
        if {![info exists resolved($target)]} {set resolved($target) [get_property NAME [source_net $local $target]]}
        lappend links $resolved($target) $sink
    }
    foreach old [array names disconnects] {execopt::disconnect_segment $old $disconnects($old)}
    dict for {sink target} [dict get $graph new_inputs] {
        if {![info exists resolved($target)]} {set resolved($target) [get_property NAME [source_net $local $target]]}
        lappend links $resolved($target) $sink
    }
    set edit_pins {};foreach {net pin} $links {lappend edit_pins $pin}
    require_disconnected $edit_pins
    log "apply_connect pins=[expr {[llength $links]/2}]"
    execopt::connect_many $links
    } result options]
    log "apply_restore_protection"
    set restored [catch {restore_boundaries [dict get $boundary properties]} restore_result restore_options]
    if {$code} {
        if {$restored} {append result "\nProtection restoration also failed: $restore_result"}
        return -options $options $result
    }
    if {$restored} {return -options $restore_options $restore_result}
    set copies [dict keys [dict get $graph replicas]]
    if {[llength $copies]} {
        set objs [get_cells $copies]
        set_property DONT_TOUCH true $objs
        set_property IS_LOC_FIXED false $objs
        set_property IS_BEL_FIXED false $objs
        set_property DONT_TOUCH true [get_nets -segments -of_objects [get_pins -of_objects $objs -filter {DIRECTION == OUT}]]
    }
    foreach key [dict keys [dict get $local copies]] {
        set_property DONT_TOUCH true [sb::cell [file dirname $key]]
        set_property DONT_TOUCH true [get_nets -segments -of_objects [sb::pin $key]]
    }
    set manifest [open $out/replicas.tsv w]; puts $manifest "kind\toriginal\treplica\ttarget_slr\tloads"
    dict for {name item} [dict get $graph replicas] {
        set key [dict get $item key]; set root [dict get $snapshot roots $key]
        puts $manifest "[dict get $root ref]\t[dict get $root cell]\t$name\t[dict get $item slr]\t[llength [dict get $graph expected $name/[dict get $root pin]]]"
    }
    close $manifest
    dict set plan local_broadcast $local
    foreach key {ce_endpoints ce_bound tracked protection} {dict set plan $key {}}
    sb::save $plan $out/plan.tcl
    return $plan
}
proc lb::scope_audit {plan out} {
    set graph [dict get $plan local_broadcast graph]
    set f [open $out/replica_scope_all.tsv w]
    puts $f "cell\ttarget_slr\tactual_slr\tloc\tbel\tdirect_pblock\tstatus"
    set failed {}
    dict for {name item} [dict get $graph replicas] {
        set target [dict get $item slr]
        set obj [sb::cell $name]
        set loc [get_property LOC $obj]
        set actual ""
        if {$loc ne ""} {set actual [sb::names [get_slrs -of_objects [get_sites -of_objects $obj]]]}
        set status [expr {$actual eq $target ? "PASS" : "FAIL"}]
        puts $f [join [list $name $target $actual $loc [get_property BEL $obj] [get_property PBLOCK $obj] $status] \t]
        if {$status eq "FAIL"} {lappend failed [list $name $target $actual $loc]}
    }
    close $f
    if {[llength $failed]} {
        # Preserve the complete placed physical state before reporting failures.
        write_checkpoint -force $out/failed_scope.dcp
        set f [open $out/replica_scope_failures.tcldict w];puts $f $failed;close $f
        error "Replica SLR scope audit failed ([llength $failed]): $failed"
    }
}

proc lb::verify {plan out placed} {
    file mkdir $out; sb::spatial_cache
    log "verify_begin placed=$placed"
    if {$placed} {scope_audit $plan $out}
    set local [dict get $plan local_broadcast]; set snapshot [dict get $local snapshot]; set graph [dict get $local graph]
    array set expected_inputs {}
    # This read-only verification has no intervening ECO/placement. Reuse its
    # full Pblock membership reads for all replicas and the floorplan snapshot.
    array set pblock_members {}
    if {[dict exists $local joint_input]} {
        set mux 0
        dict for {name item} [dict get $graph replicas] {
            if {[string match MUXF* [dict get $snapshot roots [dict get $item key] ref]]} {incr mux}
        }
        sb::require [expr {[dict get [sb::counts] mux]==[dict get $plan counts_before mux]+$mux}] "Joint MUX primitive count changed"
    }
    dict for {key root} [dict get $snapshot roots] {
        set c [dict get $root cell]
        sb::require [expr {[sb::ref $c] eq [dict get $root ref]}] "Original primitive type changed: $c"
        sb::require [expr {[sb::config $c] eq [dict get $root config]}] "Original local function changed: $c"
        dict for {pin sig} [dict get $root inputs] {set expected_inputs($c/$pin) [dict get $sig key]}
    }
    dict for {pin route} [dict get $graph moves] {
        if {[info exists expected_inputs($pin)]} {set expected_inputs($pin) [lindex $route 1]}
    }
    dict for {pin target} [dict get $graph new_inputs] {set expected_inputs($pin) $target}
    foreach pin [array names expected_inputs] {
        set key $expected_inputs($pin)
        if {[dict exists $snapshot nets $key]} {set expected [dict get $snapshot nets $key signal]} else {set expected [list drivers [list $key]]}
        sb::require [expr {[sb::signal $pin] eq $expected}] "Local input mismatch: $pin"
    }
    dict for {key pins} [dict get $graph expected] {
        set obj [source_net $local $key]
        set seen [lsort -unique [sb::names [get_pins -quiet -of_objects [get_nets -segments $obj] -filter {IS_LEAF == 1 && DIRECTION == IN}]]]
        sb::require [expr {$seen eq $pins}] "Local output sink mismatch: $key"
    }
    set f [open $out/local_positions.tsv w]; puts $f "cell\ttarget_slr\tactual_slr\tloc\tbel\tfanout\tremote_sinks"
    set drift 0
    dict for {name item} [dict get $graph replicas] {
        set root [dict get $snapshot roots [dict get $item key]]; set obj [sb::cell $name]
        sb::require [expr {[sb::ref $name] eq [dict get $root ref] && [sb::config $name] eq [dict get $root config]}] "Replica function mismatch: $name"
        sb::require [expr {![sb::one_bit [get_property IS_LOC_FIXED $obj]] && ![sb::one_bit [get_property IS_BEL_FIXED $obj]]}] "Replica acquired exact location lock: $name"
        sb::require [sb::one_bit [get_property DONT_TOUCH $obj]] "Replica unprotected: $name"
        set target [dict get $item slr]
        set pb [get_pblocks -quiet localrep_$target]
        sb::require [expr {[llength $pb]==1 && ![sb::one_bit [get_property IS_SOFT $pb]]}] "Missing hard replica SLR Pblock: target=$target objects=$pb soft=[get_property IS_SOFT $pb] all=[get_pblocks -quiet *]"
        set member_names [pblock_member_names $pb [get_property NAME $pb] pblock_members]
        sb::require [expr {[lsearch -exact $member_names $name]>=0 || [ji::in_parent $name localrep_$target]}] "Replica missing from SLR Pblock"
        if {[dict exists $local joint_input hints $name]} {
            set hint [dict get $local joint_input hints $name];set h [get_pblocks [dict get $hint pblock]]
            if {[dict exists $hint binding] && [dict get $hint binding] eq "hard_slr_only"} {
                sb::require [expr {[get_property PBLOCK $obj] eq "localrep_$target" && ![sb::one_bit [get_property IS_SOFT $h]] && [lsort [get_property GRID_RANGES $h]] eq [dict get $hint ranges]}] "Joint direct hard SLR binding changed: $name"
            } else {
                sb::require [expr {[sb::one_bit [get_property IS_SOFT $h]] && [get_property PARENT $h] eq "localrep_$target" && [lsort [get_property GRID_RANGES $h]] eq [dict get $hint ranges]}] "Joint soft region changed"
            }
        }
        if {$placed} {
            set pos [sb::position $name]
            sb::require [expr {[dict get $pos slr] eq $target}] "Replica outside target SLR: $name"
            set remote 0; set sinks [dict get $graph expected $name/[dict get $root pin]]
            foreach pin $sinks {if {[dict get [sb::position [file dirname $pin]] slr] ne $target} {incr remote}}
            incr drift $remote
            puts $f "$name\t$target\t[dict get $pos slr]\t[dict get $pos loc]\t[dict get $pos bel]\t[llength $sinks]\t$remote"
        }
    }
    close $f
    if {[dict exists $local reused_positions]} {
        set f [open $out/reused_positions.tsv w]
        puts $f "cell\ttarget_slr\tactual_slr\tloc\tbel\tstatus"
        dict for {name target} [dict get $local reused_positions] {
            # Existing identity helpers stay in their original floorplan.  Their
            # locality was a reuse premise, so verify it after every placement,
            # after routing, and again in the independent reopened checkpoint.
            set obj [sb::cell $name]
            sb::require [expr {[sb::ref $name] eq "LUT1" && [string tolower [get_property INIT $obj]] eq "2'h2"}] "Reused subtree is no longer identity: $name"
            if {$placed} {
                set pos [sb::position $name]
                set actual [dict get $pos slr]
                set status [expr {$actual eq $target ? "PASS" : "FAIL"}]
                puts $f [join [list $name $target $actual [dict get $pos loc] [dict get $pos bel] $status] \t]
                flush $f
                if {$status ne "PASS"} {close $f;error "Reused identity subtree moved outside planned SLR: $name target=$target actual=$actual"}
            } else {puts $f "$name\t$target\t\t\t\tPENDING_PLACEMENT"}
        }
        close $f
    }
    if {[dict exists $local original_pblocks]} {
        set observed [pblock_snapshot pblock_members]
        dict for {name expected} [dict get $local original_pblocks] {
            sb::require [expr {[dict exists $observed $name] && [dict get $observed $name] eq $expected}] "Original floorplan changed: $name"
        }
    }
    set f [open $out/local_structure.tsv w]; puts $f "check\tvalue"
    puts $f "exact_connectivity\tPASS\nprimitive_config_and_inputs\tPASS\noriginal_floorplan\tPASS\ncopy_slr_and_mobility\tPASS\nremote_copy_sinks\t$drift"
    close $f
}
proc lb::reports {plan out} {
    set local [dict get $plan local_broadcast]; set graph [dict get $local graph]
    set cells {}; set ff {}
    dict for {name item} [dict get $graph replicas] {
        set origin [dict get $local snapshot roots [dict get $item key] cell]
        lappend cells $origin
        if {[sb::ref $origin] in {FDRE FDSE}} {lappend ff $origin}
        if {[llength [get_cells -quiet [list $name]]]} {
            lappend cells $name
            if {[sb::ref $name] in {FDRE FDSE}} {lappend ff $name}
        }
    }
    set cells [lsort -unique $cells]; set ff [lsort -unique $ff]
    set f [open $out/local_timing_groups.tsv w]; puts $f "group\tsetup_wns\thold_whs\tendpoints"
    if {![llength $cells]} {close $f; return}
    foreach group {D CE RESET OUTPUT LUT_PATHS} {
        if {$group eq "LUT_PATHS"} {
            set luts [get_cells -quiet $cells -filter {REF_NAME =~ LUT*}]
            if {![llength $luts]} {continue}
            set objs [get_pins -of_objects $luts -filter {DIRECTION == IN}]; set way -through
        } elseif {$group eq "OUTPUT"} {set objs [get_cells $cells]; set way -from} else {
            if {![llength $ff]} {continue}
            set filter [dict get [dict create D {REF_PIN_NAME == D} CE {REF_PIN_NAME == CE} RESET {REF_PIN_NAME == R || REF_PIN_NAME == S}] $group]
            set objs [get_pins -of_objects [get_cells $ff] -filter $filter]; set way -to
        }
        set slacks {}
        foreach delay {max min} {
            set p [get_timing_paths $way $objs -delay_type $delay -max_paths 1]
            lappend slacks [expr {[llength $p] ? [get_property SLACK $p] : "NO_TIMED_PATH"}]
            report_timing $way $objs -delay_type $delay -max_paths 20 -nworst 1 -file $out/local_${group}_${delay}.rpt
        }
        puts $f "$group\t[join $slacks \t]\t[llength $objs]"
    }
    close $f
}
proc lb::install {} {
    rename ::sb::scan ::sb::legacy_scan
    proc ::sb::scan {out path_limit min_fanout} {return [lb::discover $out $min_fanout]}
    rename ::sb::apply ::sb::legacy_apply
    proc ::sb::apply {plan out} {
        if {[dict exists $plan local_broadcast]} {return [lb::apply $plan $out]}
        return [legacy_apply $plan $out]
    }
    rename ::sb::verify ::sb::legacy_verify
    proc ::sb::verify {plan out placed} {
        legacy_verify $plan $out $placed
        if {[dict exists $plan local_broadcast]} {lb::verify $plan $out $placed}
    }
    rename ::sb::reports ::sb::legacy_reports
    proc ::sb::reports {plan out final} {
        legacy_reports $plan $out $final
        if {[dict exists $plan local_broadcast]} {lb::reports $plan $out}
    }
    rename ::rf::legacy_exclusions ::rf::original_legacy_exclusions
    proc ::rf::legacy_exclusions {plan} {
        set result [original_legacy_exclusions $plan]
        if {[dict exists $plan local_broadcast]} {lappend result {*}[dict keys [dict get $plan local_broadcast snapshot nets]]}
        return $result
    }
}
