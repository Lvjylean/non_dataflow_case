# Bounded identity ECOs. Preserve cells, never lock fanout nets against replication.
namespace eval hf2 {
    variable protection_cache [dict create]
    variable protection_self [dict create]
    variable protection_snapshot_ready 0
    variable identity_manifest ""
    variable post_helpers 0
    variable locations; array set locations {}
    variable site_regions; array set site_regions {}
    variable free_sites [dict create]
    variable region_slrs [dict create]
    variable placement_cache_ready 0
}
proc hf2::pin_cell_name {pin} {return [string range $pin 0 [expr {[string last / $pin]-1}]]}
proc hf2::site_key {pin} {
    variable locations
    set name [pin_cell_name $pin]
    if {![info exists locations($name)]} {
        set cell [get_cells -quiet [list $name]]
        set locations($name) [get_property LOC $cell]
    }
    set site $locations($name)
    if {$site eq ""} {return UNPLACED:$name}
    return $site
}
proc hf2::select_sinks {item placed} {
    set move {}; set keep {}; set blocked_sites [dict create]; set reasons [dict create]
    if {[dict exists $item sink_kinds]} {
        set kinds [dict get $item sink_kinds]
        if {[lsort [dict keys $kinds]] ne [lsort [dict get $item sinks]]} {error STALE_SINK_KIND_INVENTORY}
    } else {
        set kinds [dict create]
        foreach name [dict get $item sinks] {dict set kinds $name [sink_kind [get_pins [list $name]]]}
    }
    set move_map [dict create]; set keep_map [dict create]
    dict for {name reason} $kinds {
        if {$reason eq "ORDINARY"} {
            set reason [cell_protection_name [pin_cell_name $name] 1]
            if {[string match */inst/i_synth/* $name]} {set reason PROTECTED_IP_MANUAL_EDIT}
        }
        if {$reason eq ""} {
            dict set move_map $name 1
        } else {
            dict set keep_map $name 1; dict incr reasons $reason
            if {$placed} {dict set blocked_sites [site_key $name] 1}
        }
    }
    set move [lsort [dict keys $move_map]]
    set keep [lsort [dict keys $keep_map]]
    # Do not split a packed site's shared CE/reset/site pin between two nets.
    if {$placed && [dict size $blocked_sites]} {
        set eligible {}
        foreach pin $move {
            if {[dict exists $blocked_sites [site_key $pin]]} {
                lappend keep $pin; dict incr reasons SHARED_SITE_WITH_RETAINED_PIN
            } else {lappend eligible $pin}
        }
        set move $eligible
    }
    return [list $move $keep $reasons]
}
proc hf2::placement_cache {} {
    variable locations; variable site_regions; variable free_sites; variable region_slrs
    variable placement_cache_ready
    if {$placement_cache_ready} {return}
    array unset locations; array set locations {}
    array unset site_regions; array set site_regions {}
    set used [dict create]
    set cells [get_cells -hier -filter {IS_PRIMITIVE == 1}]
    foreach name [plain_values NAME $cells] site [plain_values LOC $cells] {
        set locations($name) $site
        if {$site ne ""} {dict set used $site 1}
    }
    foreach cr [get_clock_regions] {
        set name [get_property NAME $cr]
        dict set region_slrs $name [get_property NAME [get_slrs -of_objects $cr]]
        set available {}
        foreach site [f96::plain_names [get_sites -of_objects $cr]] {
            set site_regions($site) $name
            if {[string match SLICE_* $site] && ![dict exists $used $site]} {lappend available $site}
        }
        dict set free_sites $name [lsort -dictionary $available]
    }
    set placement_cache_ready 1
}
proc hf2::rank_regions {pins driver} {
    variable site_regions; variable region_slrs; variable free_sites
    set sx 0; set sy 0; set n 0; set slrs [dict create]
    foreach pin [concat $pins [list $driver]] {
        set site [site_key $pin]
        if {![info exists site_regions($site)]} {continue}
        set region $site_regions($site)
        regexp {X([0-9]+)Y([0-9]+)$} $region unused x y
        incr sx $x; incr sy $y; incr n
        dict incr slrs [dict get $region_slrs $region]
    }
    if {!$n} {return {}}
    set best_slr {}; set best_count -1
    dict for {slr count} $slrs {if {$count > $best_count} {set best_slr $slr; set best_count $count}}
    set ranked {}
    dict for {region sites} $free_sites {
        if {![llength $sites] || [dict get $region_slrs $region] ne $best_slr} {continue}
        regexp {X([0-9]+)Y([0-9]+)$} $region unused x y
        lappend ranked [list [expr {abs($n*$x-$sx)+abs($n*$y-$sy)}] $region]
    }
    return [lsort -integer -index 0 $ranked]
}
proc hf2::place_helpers {plan driver channel} {
    variable cfg; variable free_sites; variable locations
    placement_cache
    foreach entry $plan {
        lassign $entry name level hint group
        set attempts 0; set success 0
        foreach ranked [rank_regions $group $driver] {
            set region [lindex $ranked 1]
            while {[llength [dict get $free_sites $region]] && $attempts < [dict get $cfg local_site_attempts]} {
                set pool [dict get $free_sites $region]; set site [lindex $pool 0]
                dict set free_sites $region [lrange $pool 1 end]
                incr attempts
                # Never use -quiet: it turns placement failures into TCL_OK.
                set rc [catch {place_cell [list $name $site]} detail]
                set cell [get_cells [list $name]]
                set actual [get_property LOC $cell]; set bel [get_property BEL $cell]
                if {!$rc && $actual eq $site && $bel ne ""} {
                    set locations($name) $actual
                    puts $channel "$name\t$site\t$bel\t$attempts\tPLACED"
                    set success 1; break
                }
                if {$actual ne ""} {unplace_cell [list $name]}
            }
            if {$success || $attempts >= [dict get $cfg local_site_attempts]} {break}
        }
        if {!$success} {error "LOCAL_PLACEMENT_UNAVAILABLE:$name"}
    }
}
proc hf2::discard_helpers {names net_names} {
    variable locations; variable placement_cache_ready
    if {[llength $names]} {
        set_property DONT_TOUCH false [get_cells $names]
        remove_cell [get_cells $names]
        remove_net [get_nets $net_names]
    }
    foreach name $names {unset -nocomplain locations($name)}
    # Rebuild after a failed batch so freed sites are not permanently consumed.
    set placement_cache_ready 0
}
proc hf2::disconnect_subset {driver names} {
    set wanted [dict create]; foreach name $names {dict set wanted $name 1}
    set pairs {}; set found {}
    foreach net [get_nets -quiet -segments -of_objects $driver] {
        set members {}
        foreach name [f96::plain_names [get_pins -quiet -of_objects $net -filter {DIRECTION == IN && IS_LEAF == 1}]] {
            if {[dict exists $wanted $name]} {lappend members $name; lappend found $name}
        }
        if {[llength $members]} {lappend pairs [list [get_property NAME $net] $members]}
    }
    if {[lsort $found] ne [lsort $names]} {error SELECTIVE_SEGMENT_COVERAGE_MISMATCH}
    foreach pair $pairs {
        lassign $pair net members
        for {set i 0} {$i < [llength $members]} {incr i 512} {
            disconnect_net -net [get_nets [list $net]] -pinlist [f96::pin_objects [lrange $members $i [expr {$i+511}]]]
        }
    }
}
proc hf2::edit_tree {item plan frontier keep out channels placed} {
    variable identity_manifest
    lassign $channels app branches original edges placement
    set driver [dict get $item driver]; set dname [dict get $item driver_name]
    set before [lsort [f96::plain_names [f96::loads $driver]]]
    if {$before ne [lsort [dict get $item sinks]]} {error "Stale discovery: $dname"}
    set root [get_nets -of_objects $driver]
    if {[llength $root] != 1} {error "Expected one direct net: $dname"}
    set names {}; set net_names {}; set wanted {}
    foreach entry $plan {
        lassign $entry name level hint group
        lappend names $name; lappend net_names ${name}_out
        if {$level == 0} {lappend wanted {*}$group}
    }
    if {![llength $plan]} {return NO_EDIT_NEEDED}
    if {[llength [get_cells -quiet $names]] || [llength [get_nets -quiet $net_names]]} {error HELPER_COLLISION}
    f96::fast_create $names $net_names
    set_property INIT 2'h2 [get_cells $names]
    set_property DONT_TOUCH true [get_cells $names]
    if {$placed && [catch {place_helpers $plan $dname $placement} why]} {
        # No original net has been rewired yet; placement failure is an annotation.
        discard_helpers $names $net_names
        return $why
    }
    set unlocked {}
    set sink_cells {}; foreach pin $wanted {lappend sink_cells [pin_cell_name $pin]}
    foreach name [lsort -unique [concat [list [pin_cell_name $dname]] $sink_cells]] {
        if {[string match f96_identity_* $name] && [lsearch -exact $names $name] < 0 && [flag [get_cells [list $name]] DONT_TOUCH]} {
            lappend unlocked $name
        }
    }
    if {[llength $unlocked]} {set_property DONT_TOUCH false [get_cells $unlocked]}
    set rc [catch {
        disconnect_subset $driver $wanted
        f96::fast_connect $plan $frontier $root
    } detail options]
    if {[llength $unlocked]} {set_property DONT_TOUCH true [get_cells $unlocked]}
    if {$rc} {return -options $options $detail}
    set graph [dict create]
    foreach entry $plan {
        lassign $entry name level hint group
        set actual [lsort [f96::plain_names [f96::loads [get_pins [list $name/O]]]]]
        if {$actual ne [lsort $group]} {error "Branch connectivity mismatch: $name"}
        dict set graph $name/I0 $actual
        puts $branches "$name\t$dname\t$level\t$hint\t[llength $group]"
        puts $edges "$name\t[list $group]"
    }
    set expected [lsort [concat $frontier $keep]]
    if {[lsort [f96::plain_names [f96::loads $driver]]] ne $expected} {error "Root connectivity mismatch: $dname"}
    set pending $expected; set recovered {}
    while {[llength $pending]} {
        set next {}
        foreach pin $pending {
            if {[dict exists $graph $pin]} {lappend next {*}[dict get $graph $pin]} else {lappend recovered $pin}
        }
        set pending $next
    }
    if {[lsort $recovered] ne $before} {error "Original sink coverage mismatch: $dname"}
    puts $original "$dname\t[list $before]"
    puts $app "$dname\t[dict get $item ref]\t[llength $before]\t[llength $expected]\t[llength $plan]\t[expr {1+[lindex [lindex $plan end] 1]}]\tEXACT_PASS"
    set ledger [open $identity_manifest a]
    foreach name $names {puts $ledger "$name\t$dname\t[file tail $out]"}
    close $ledger
    return EXACT_PASS
}
proc hf2::apply_stage {items out placed} {
    variable cfg; variable post_helpers; variable identity_manifest
    if {$identity_manifest eq "" || ![file isfile $identity_manifest]} {error MISSING_IDENTITY_MANIFEST}
    file mkdir $out
    set app [open $out/application.tsv w]; puts $app "driver\tref\tbefore\tafter\tnew_luts\tlevels\tcoverage"
    set bf [open $out/branches.tsv w]; puts $bf "cell\troot\tlevel\thint\tloads"
    set original [open $out/original_sinks.tcllist.tsv w]; puts $original "driver\tsinks_tcl_list"
    set ef [open $out/new_edges.tcllist.tsv w]; puts $ef "helper\tsinks_tcl_list"
    set pf [open $out/placement.tsv w]; puts $pf "cell\tsite\tbel\tattempts\tstatus"
    set sf [open $out/dispatch.tsv w]; puts $sf "driver\tref\tstatus\tretained_loads\tdetail"
    set channels [list $app $bf $original $ef $pf]
    foreach channel [concat $channels [list $sf]] {flush $channel}
    f96::phase "identity_prepare $out placed=$placed items=[llength $items]"
    set before_ff [ff_count]; set prepared {}
    set saved_serial $::f96::serial; set saved_created $::f96::created; set saved_post $post_helpers
    set started_edits 0
    set rc [catch {
        prime_protection $items
        set item_index 0
        foreach item $items {
            incr item_index
            if {$item_index % 25 == 1} {f96::phase "identity_prepare_progress $out items=$item_index"}
            if {[llength [dict get $item sinks]] <= [dict get $cfg memory_target]} {continue}
            set action [classify [dict get $item ref] [pin_cell_name [dict get $item driver_name]]]
            set reason [protection_reason $item [expr {$action eq "OWNED_IDENTITY" ? $action : "MANUAL_IDENTITY"}]]
            if {$action eq "UNSUPPORTED"} {set reason UNSUPPORTED_DRIVER}
            if {$reason ne ""} {puts $sf "[dict get $item driver_name]\t[dict get $item ref]\tDEFERRED\t0\t$reason"; continue}
            if {$placed && ![dict get $cfg post_place_lut_budget]} {
                puts $sf "[dict get $item driver_name]\t[dict get $item ref]\tDEFERRED\t0\tPOST_PLACE_HELPER_BUDGET"; continue
            }
            if {$placed} {placement_cache}
            lassign [select_sinks $item $placed] move keep why
            set serial $::f96::serial; set created $::f96::created
            set rc [catch {tree_plan $move [llength $keep] $placed} plan_result]
            set needed [expr {$::f96::created-$created}]
            if {!$rc && $::f96::created > [dict get $cfg memory_lut_budget]} {set rc 1; set plan_result GLOBAL_HELPER_BUDGET}
            if {!$rc && $placed && $post_helpers+$needed > [dict get $cfg post_place_lut_budget]} {set rc 1; set plan_result POST_PLACE_HELPER_BUDGET}
            if {$rc} {
                set ::f96::serial $serial; set ::f96::created $created
                if {!$placed && $plan_result eq "GLOBAL_HELPER_BUDGET"} {error "Identity LUT budget exhausted before edits"}
                puts $sf "[dict get $item driver_name]\t[dict get $item ref]\tDEFERRED\t[llength $keep]\t$plan_result"; continue
            }
            lassign $plan_result plan frontier levels
            if {$placed} {incr post_helpers $needed}
            lappend prepared [list $item $plan $frontier $keep $why]
        }
        # Planning/budget checks finish before the first netlist mutation.
        f96::phase "identity_edit_begin $out batches=[llength $prepared]"
        set started_edits 1
        foreach entry $prepared {
            lassign $entry item plan frontier keep why
            set result [edit_tree $item $plan $frontier $keep $out $channels $placed]
            if {$result ni {EXACT_PASS NO_EDIT_NEEDED}} {
                incr ::f96::created -[llength $plan]
                if {$placed} {incr post_helpers -[llength $plan]}
            }
            puts $sf "[dict get $item driver_name]\t[dict get $item ref]\t$result\t[llength $keep]\t$why"
        }
        set after_ff [ff_count]
        set f [open $out/register_check.tsv w]
        puts $f "before_ff\tafter_ff\tmanual_pipeline_stages\n$before_ff\t$after_ff\t0"; close $f
        if {$before_ff != $after_ff} {error MANUAL_ECO_CHANGED_REGISTER_COUNT}
    } detail options]
    foreach f [concat $channels [list $sf]] {close $f}
    if {$rc && !$started_edits} {
        set ::f96::serial $saved_serial; set ::f96::created $saved_created; set post_helpers $saved_post
    }
    if {$rc} {return -options $options $detail}
}
proc hf2::apply_memory {items out} {apply_stage $items $out 0}
proc hf2::apply_residual {items out} {apply_stage $items $out 1}
proc hf2::audit_identities {out} {
    variable identity_manifest
    file mkdir $out
    if {$identity_manifest eq "" || ![file isfile $identity_manifest]} {error MISSING_IDENTITY_MANIFEST}
    set f [open $identity_manifest r]; gets $f; array set expected {}; set bad 0
    while {[gets $f line] >= 0} {
        set name [lindex [split $line \t] 0]
        if {$name eq "" || [info exists expected($name)]} {incr bad}
        set expected($name) 1
    }; close $f
    # Native fanout copies and BUFG promotion inherit our name prefix. Only the
    # exact ledger identifies manual helpers; native extras need explicit provenance.
    set prefixed [get_cells -quiet f96_identity_*]
    set helpers {}; array set actual {}; set replicas 0; set buffers 0; set unknown 0
    set details [open $out/identity_cells.tsv w]
    puts $details "cell\tref\tinit\tdont_touch\tcategory\torig_cell\tphys_opt_modified"
    foreach name [f96::plain_names $prefixed] ref [f96::values REF_NAME $prefixed] init [f96::values INIT $prefixed] flag [f96::values DONT_TOUCH $prefixed] {
        set actual($name) 1; set origin ""; set modified ""; set category MANUAL
        if {[info exists expected($name)]} {
            lappend helpers $name
            if {$ref ne "LUT1" || $init ne "2'h2" || ![truth $flag]} {incr bad}
        } else {
            set cell [get_cells [list $name]]
            set origin [get_property -quiet ORIG_CELL_NAME $cell]
            set modified [get_property -quiet PHYS_OPT_MODIFIED $cell]
            if {$ref eq "LUT1" && [info exists expected($origin)] && [string match *FANOUT_OPT* $modified]} {
                set category NATIVE_IDENTITY_REPLICA; incr replicas; lappend helpers $name
                if {$init ne "2'h2" || ![truth $flag]} {incr bad}
            } elseif {[string match BUFG* $ref] && [string match *BUFG_OPT* $modified] &&
                      [regexp {^(f96_identity_[0-9]+)_bufg_place(?:_[0-9]+)?$} $name unused parent] && [info exists expected($parent)]} {
                set category NATIVE_BUFFER; incr buffers
            } else {set category UNRECOGNIZED_PREFIXED_CELL; incr unknown; incr bad}
        }
        puts $details "$name\t$ref\t$init\t$flag\t$category\t$origin\t$modified"
    }
    foreach name [array names expected] {if {![info exists actual($name)]} {incr bad; puts $details "$name\t\t\t\tMISSING_MANUAL\t\t"}}
    close $details
    set protected_outputs 0
    if {[llength $helpers]} {
        set nets [get_nets -quiet -segments -of_objects [get_pins -of_objects [get_cells $helpers] -filter {DIRECTION == OUT}]]
        foreach flag [f96::values DONT_TOUCH $nets] {if {[truth $flag]} {incr protected_outputs}}
    }
    set f [open $out/identity_summary.tsv w]
    puts $f "helpers\tidentity_or_protection_failures\tregisters\tnew_pipeline_stages\tprotected_helper_output_segments\tnative_identity_replicas\tnative_buffers\tunrecognized_prefixed_cells\tprefixed_cells"
    puts $f "[array size expected]\t$bad\t[ff_count]\t0\t$protected_outputs\t$replicas\t$buffers\t$unknown\t[llength $prefixed]"; close $f
    if {$bad} {error IDENTITY_CELL_MANIFEST_OR_FUNCTION_MISMATCH}
    if {$protected_outputs} {error IDENTITY_OUTPUT_NET_BLOCKS_NATIVE_REPLICATION}
}
proc hf2::assert_placed_helpers {} {
    foreach name [f96::plain_names [get_cells -quiet f96_identity_*]] {
        set cell [get_cells [list $name]]
        if {[get_property LOC $cell] eq "" || [get_property BEL $cell] eq ""} {error "Unplaced helper: $name"}
    }
}
