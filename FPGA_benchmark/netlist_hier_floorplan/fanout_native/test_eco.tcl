# Connectivity model for selective ECO regression; native Vivado is NOT invoked.
source [file dirname [file normalize [info script]]]/core.tcl
proc check {condition message} {if {![uplevel 1 [list expr $condition]]} {error $message}}
set count 0
proc case {name body} {uplevel 1 $body; incr ::count; puts "PASS: $name"}
set out [file join /tmp hf2-eco-[pid]]; file mkdir $out
proc reset_model {} {
    set ::cells [dict create]; set ::pins [dict create]; set ::nets [dict create]; set ::attrs [dict create]; set ::trace {}
    set ::f96::serial 0; set ::f96::created 0; set ::hf2::post_helpers 0
    set ::hf2::protection_cache [dict create]; set ::hf2::protection_self [dict create]; set ::hf2::protection_snapshot_ready 0
    array unset ::hf2::locations; array set ::hf2::locations {}; set ::hf2::placement_cache_ready 0
    set ::hf2::identity_manifest $::out/manifest.tsv
    set f [open $::hf2::identity_manifest w]; puts $f "cell\troot\tstage"; close $f
    hf2::configure {native_target 96 memory_target 96 refinement_passes 1 memory_lut_budget 50000 post_place_lut_budget 4096 upstream_levels 1}
}
proc cell {name ref {site {}}} {
    dict set ::cells $name [dict create NAME $name REF_NAME $ref PRIMITIVE_LEVEL LEAF DONT_TOUCH false ASYNC_REG false LOC $site BEL [expr {$site eq "" ? "" : "A6LUT"}]]
}
proc pin {name dir {clock 0}} {dict set ::pins $name [dict create DIRECTION $dir IS_CLOCK $clock IS_LEAF 1 REF_PIN_NAME [lindex [split $name /] end] NET {}]}
proc link {net pins} {
    if {![dict exists $::nets $net]} {dict set ::nets $net {}}
    foreach p $pins {
        if {[dict get $::pins $p NET] ne ""} {error "Pin already connected: $p"}
        dict lappend ::nets $net $p; dict set ::pins $p NET $net
    }
}
proc option {args name} {set i [lsearch -exact $args $name]; if {$i < 0} {return {}}; return [lindex $args [expr {$i+1}]]}
proc get_cells {args} {
    set of [option $args -of_objects]; set names {}
    if {$of ne ""} {
        foreach p $of {
            if {[dict exists $::pins $p]} {lappend names [hf2::pin_cell_name $p]} elseif {[dict exists $::cells $p]} {lappend names $p}
        }
    } elseif {[lsearch -exact $args -hier] >= 0} {set names [dict keys $::cells]} else {
        foreach pattern [lindex $args end] {
            foreach name [dict keys $::cells] {if {$name eq $pattern || [string match $pattern $name]} {lappend names $name}}
        }
    }
    set result {}
    foreach name [lsort -unique $names] {
        if {![dict exists $::cells $name]} {continue}
        if {[string match {*PRIMITIVE_LEVEL == INTERNAL*} [option $args -filter]] && [dict get $::cells $name PRIMITIVE_LEVEL] ne "INTERNAL"} {continue}
        if {[string match *FD* [option $args -filter]] && ![string match FD* [dict get $::cells $name REF_NAME]]} {continue}
        lappend result $name
    }
    return $result
}
proc get_pins {args} {
    set of [option $args -of_objects]; set names {}
    if {$of ne ""} {
        foreach o $of {
            if {[dict exists $::nets $o]} {lappend names {*}[dict get $::nets $o]} elseif {[dict exists $::cells $o]} {
                foreach p [dict keys $::pins] {if {[hf2::pin_cell_name $p] eq $o} {lappend names $p}}
            }
        }
    } else {foreach n [lindex $args end] {if {[dict exists $::pins $n]} {lappend names $n}}}
    set result {}; set filter [option $args -filter]
    foreach n [lsort -unique $names] {
        if {[regexp {DIRECTION == (IN|OUT)} $filter unused dir] && [dict get $::pins $n DIRECTION] ne $dir} {continue}
        if {[string match {*IS_CLOCK == 0*} $filter] && [dict get $::pins $n IS_CLOCK]} {continue}
        lappend result $n
    }
    return $result
}
proc get_nets {args} {
    set of [option $args -of_objects]; set names {}
    if {$of ne ""} {
        foreach o $of {
            if {[dict exists $::pins $o]} {set n [dict get $::pins $o NET]; if {$n ne ""} {lappend names $n}} elseif {[dict exists $::nets $o]} {lappend names $o}
        }
    } elseif {[lsearch -exact $args -hier] >= 0} {
        foreach n [dict keys $::nets] {if {[llength [dict get $::nets $n]] > 96} {lappend names $n}}
    } else {foreach n [lindex $args end] {if {[dict exists $::nets $n]} {lappend names $n}}}
    return [lsort -unique $names]
}
proc get_clock_regions {args} {return {}}
proc get_ports {args} {return {}}
proc get_clocks {args} {return {}}
proc get_site_pins {args} {return {}}
proc get_property {args} {
    lassign [lrange $args end-1 end] key objects
    set values {}
    foreach o $objects {
        set value false
        if {$key eq "NAME"} {set value $o} elseif {[dict exists $::attrs $o $key]} {set value [dict get $::attrs $o $key]} elseif {[dict exists $::cells $o $key]} {set value [dict get $::cells $o $key]} elseif {[dict exists $::pins $o $key]} {set value [dict get $::pins $o $key]} elseif {$key eq "PBLOCK"} {set value {}}
        lappend values $value
    }
    if {[llength $objects] == 1} {return [lindex $values 0]}
    return $values
}
proc set_property {key value objects} {
    foreach o $objects {dict set ::attrs $o $key $value; lappend ::trace [list SET $o $key $value]}
}
proc create_cell {args} {
    set ref [option $args -reference]
    foreach n [lindex $args end] {cell $n $ref; pin $n/I0 IN; pin $n/O OUT; lappend ::trace [list CREATE $n]}
}
proc create_net {names} {foreach n $names {dict set ::nets $n {}}}
proc connect_net {args} {
    set pairs [option $args -dict]
    foreach {net p} $pairs {link $net [list $p]}
}
proc disconnect_net {args} {
    set net [option $args -net]; set names [option $args -pinlist]
    foreach p $names {
        check {[dict get $::pins $p NET] eq $net} "Disconnect selected wrong net"
        dict set ::pins $p NET {}
        set ls [dict get $::nets $net]; set i [lsearch -exact $ls $p]; dict set ::nets $net [lreplace $ls $i $i]
    }
}
proc remove_cell {names} {
    foreach name $names {
        foreach p [dict keys $::pins] {if {[hf2::pin_cell_name $p] eq $name} {check {[dict get $::pins $p NET] eq ""} "Rollback removed connected helper"; dict unset ::pins $p}}
        dict unset ::cells $name
        if {[dict exists $::attrs $name]} {dict unset ::attrs $name}
    }
}
proc remove_net {names} {foreach n $names {check {![llength [dict get $::nets $n]]} "Rollback deleted original edges"; dict unset ::nets $n}}
proc source_of {p} {
    set net [dict get $::pins $p NET]; set drivers {}
    foreach q [dict get $::nets $net] {if {[dict get $::pins $q DIRECTION] eq "OUT"} {lappend drivers $q}}
    check {[llength $drivers] == 1} "Expected one driver"
    set d [lindex $drivers 0]; set c [hf2::pin_cell_name $d]
    if {[dict get $::cells $c REF_NAME] eq "LUT1"} {
        check {[get_property INIT $c] eq "2'h2"} "Helper is not an identity"
        return [source_of $c/I0]
    }
    return $d
}
proc fixture {n {extra 0}} {
    cell source FDRE; pin source/Q OUT; pin source/R IN
    cell reset FDRE; pin reset/Q OUT; link reset_net {reset/Q source/R}
    set sinks {}
    for {set i 0} {$i < $n} {incr i} {cell s$i FDRE SLICE_X${i}Y0; pin s$i/D IN; lappend sinks s$i/D}
    if {$extra} {
        cell clockbuf BUFGCE; pin clockbuf/I IN 1; lappend sinks clockbuf/I
        cell chain CARRY8; pin chain/CI IN; lappend sinks chain/CI
        cell user FDRE; pin user/D IN; set_property DONT_TOUCH true user; lappend sinks user/D
    }
    link original [concat {source/Q} $sinks]
    return [dict create driver source/Q driver_name source/Q ref FDRE sinks $sinks]
}
case input_net_guard_detects_original_regression {
    reset_model; set item [fixture 110]
    set_property DONT_TOUCH true reset_net
    check {[hf2::protection_reason $item NATIVE] eq "EXISTING_INPUT_NET_DONT_TOUCH"} "Input lock was ignored"
    check {[get_property DONT_TOUCH reset_net]} "Original protection was removed"
}
case actual_scan_keeps_mixed_net_and_cascade {
    reset_model; set item [fixture 110 1]
    set found [hf2::scan $out/scan]
    check {[llength $found] == 1} "Mixed high-fanout driver disappeared"
    set row [lindex $found 0]
    check {[llength [dict get $row keep_sinks]] == 2} "Clock/cascade branch was not retained"
    lassign [hf2::actions $found $out/actions] n m o
    check {![llength $n] && [llength $o] == 1} "Mixed net reached unrestricted native replication"
}
case selective_rewire_preserves_function_and_existing_locks {
    reset_model; set item [fixture 110 1]
    hf2::apply_memory [list $item] $out/edit
    foreach p [dict get $item sinks] {check {[source_of $p] eq "source/Q"} "Identity graph changed original function"}
    foreach p {clockbuf/I chain/CI user/D} {check {[dict get $::pins $p NET] eq "original"} "Reserved branch was rewired"}
    check {[get_property DONT_TOUCH user]} "User protection removed"
    foreach n [dict keys $::nets] {check {![get_property DONT_TOUCH $n]} "New signal-net lock blocks downstream replication"}
    check {[hf2::protection_reason $item NATIVE] eq ""} "Helper edit blocked native driver"
    hf2::audit_identities $out/audit
    foreach p [dict keys $::pins] {
        if {[string match f96_identity_*/O $p]} {check {[llength [f96::loads $p]] <= 96} "Helper exceeds threshold"}
    }
}
case expected_helper_manifest_detects_missing_cell {
    set name [lindex [get_cells f96_identity_*] 0]
    dict unset ::cells $name
    check {[catch {hf2::audit_identities $out/missing}]} "Missing helper silently passed audit"
}
case native_prefix_objects_have_separate_verified_provenance {
    reset_model; hf2::apply_memory [list [fixture 110]] $out/native_prefix
    set parent [lindex [get_cells f96_identity_*] 0]
    set replica ${parent}_replica; cell $replica LUT1
    set_property INIT 2'h2 $replica; set_property DONT_TOUCH true $replica
    set_property ORIG_CELL_NAME $parent $replica; set_property PHYS_OPT_MODIFIED FANOUT_OPT $replica
    set buffer ${parent}_bufg_place; cell $buffer BUFGCE
    set_property PHYS_OPT_MODIFIED BUFG_OPT $buffer
    hf2::audit_identities $out/native_prefix_audit
    set f [open $out/native_prefix_audit/identity_summary.tsv r]; gets $f header; gets $f line; close $f
    check {[lindex [split $line \t] 0] == 2 && [lindex [split $line \t] 5] == 1 && [lindex [split $line \t] 6] == 1} "Native objects counted as manual helpers"
    set_property INIT 2'h1 $replica
    check {[catch {hf2::audit_identities $out/bad_replica}]} "Corrupted native identity accepted"
    set_property INIT 2'h2 $replica
    dict unset ::cells $parent
    check {[catch {hf2::audit_identities $out/native_cannot_hide_missing}]} "Native copy hid missing original helper"
}
case unexpected_prefix_without_native_provenance_rejected {
    reset_model; hf2::apply_memory [list [fixture 110]] $out/unknown_prefix
    cell f96_identity_999 LUT1
    set_property INIT 2'h2 f96_identity_999; set_property DONT_TOUCH true f96_identity_999
    check {[catch {hf2::audit_identities $out/unknown_prefix_audit}]} "Unledgered manual helper accepted"
}
case missing_contract_rejected_before_edit {
    reset_model; set item [fixture 110]; set snapshot $::nets
    set ::hf2::identity_manifest {}
    check {[catch {hf2::apply_memory [list $item] $out/no_contract}]} "Missing manifest accepted"
    check {$snapshot eq $::nets && ![llength [get_cells f96_identity_*]]} "Missing contract changed graph"
}
case global_budget_rejected_before_mutation {
    reset_model; set item [fixture 250]
    hf2::configure {memory_lut_budget 1}
    set snapshot $::nets
    check {[catch {hf2::apply_memory [list $item] $out/budget}]} "Insufficient budget was accepted"
    check {$snapshot eq $::nets && ![llength [get_cells f96_identity_*]]} "Budget failure partly rewired graph"
    check {$::f96::created == 0 && $::f96::serial == 0} "Budget preflight leaked allocation"
}
case carry_output_supported_without_touching_cascade {
    reset_model; set item [fixture 110 1]
    dict set ::cells source REF_NAME CARRY8; dict set item ref CARRY8
    lassign [hf2::actions [list $item] $out/carry_actions] n m other
    check {[llength $other] == 1} "Carry was not dispatched"
    hf2::apply_memory $other $out/carry
    check {[dict get $::pins chain/CI NET] eq "original"} "Carry chain rewired"
}
case upstream_small_driver_is_marked_before_replication {
    reset_model; set item [fixture 100]
    hf2::mark_upstream [list $item] $out/upstream
    check {[get_property FORCE_MAX_FANOUT reset_net] == 96} "Small upstream reset source omitted"
}
# Force local placement failure before any original endpoint rewiring.
rename hf2::place_helpers hf2::saved_place_helpers
proc hf2::place_helpers {plan driver channel} {error LOCAL_PLACEMENT_UNAVAILABLE}
case failed_local_placement_preserves_original_graph {
    reset_model; set item [fixture 110]
    set snapshot $::nets
    hf2::apply_residual [list $item] $out/failed_place
    check {$::nets eq $snapshot && ![llength [get_cells f96_identity_*]]} "Failed placement changed design"
    check {$::f96::created == 0 && $::hf2::post_helpers == 0} "Failed placement consumed helper budget"
}
case late_budget_is_annotation_without_mutation {
    reset_model; set item [fixture 110]; set snapshot $::nets
    hf2::configure {post_place_lut_budget 0}
    hf2::apply_residual [list $item] $out/zero_budget
    check {$::nets eq $snapshot} "Disabled local budget changed graph"
}
rename hf2::place_helpers {}; rename hf2::saved_place_helpers hf2::place_helpers
rename hf2::placement_cache hf2::saved_placement_cache
rename hf2::rank_regions hf2::saved_rank_regions
proc hf2::placement_cache {} {set ::hf2::free_sites [dict create X3Y8 {SLICE_X1Y1 SLICE_X1Y2}]}
proc hf2::rank_regions {pins driver} {return {{0 X3Y8}}}
proc place_cell {pair} {
    lassign $pair name site
    check {[string match f96_identity_* $name]} "Placer moved an original cell"
    lappend ::trace [list PLACE_CELL $name $site]
    if {$::placement_result eq "success"} {dict set ::cells $name LOC $site; dict set ::cells $name BEL A6LUT}
}
proc unplace_cell {names} {foreach n $names {dict set ::cells $n LOC {}; dict set ::cells $n BEL {}}}
case placement_return_code_is_not_a_legality_certificate {
    reset_model; set item [fixture 110]; set snapshot $::nets; set ::placement_result no_location
    hf2::configure {local_site_attempts 1}
    hf2::apply_residual [list $item] $out/lying_placer
    check {$::nets eq $snapshot && ![llength [get_cells f96_identity_*]]} "Unplaced helpers reached route"
}
case local_repair_places_only_new_cells_and_handles_final_generation {
    reset_model; set item [fixture 110]; set ::placement_result success
    set original_sites [dict create]; foreach c [dict keys $::cells] {dict set original_sites $c [dict get $::cells $c LOC]}
    hf2::apply_residual [list $item] $out/late_success
    hf2::assert_placed_helpers
    foreach p [dict get $item sinks] {check {[source_of $p] eq "source/Q"} "Late repair changed function"}
    dict for {c site} $original_sites {check {[dict get $::cells $c LOC] eq $site} "Existing placement moved"}
    check {[llength [f96::loads source/Q]] < 100} "Final-generation root not bounded"
}
case packed_site_is_never_split_across_identity_drivers {
    reset_model; set item [fixture 110]; set ::placement_result success
    dict set ::cells s0 LOC SLICE_X20Y20; dict set ::cells s109 LOC SLICE_X20Y20
    hf2::apply_residual [list $item] $out/shared_site
    check {[dict get $::pins s0/D NET] eq [dict get $::pins s109/D NET]} "One packed site split across helper outputs"
}
case original_input_lock_is_retained_during_manual_fallback {
    reset_model; set item [fixture 110]; set ::placement_result success
    set_property DONT_TOUCH true reset_net
    hf2::apply_residual [list $item] $out/locked_input_fallback
    check {[get_property DONT_TOUCH reset_net]} "Fallback removed original input protection"
    foreach p [dict get $item sinks] {check {[source_of $p] eq "source/Q"} "Fallback changed source"}
}
case oversized_atomic_site_is_reported_without_edit {
    reset_model; set item [fixture 110]; set snapshot $::nets
    foreach name [dict keys $::cells] {if {[string match {s[0-9]*} $name]} {dict set ::cells $name LOC SLICE_X20Y20}}
    hf2::apply_residual [list $item] $out/oversize_site
    check {$::nets eq $snapshot && ![llength [get_cells f96_identity_*]]} "Oversized packed atom was split"
}
case sparse_snapshot_preserves_ancestor_and_refreshes_after_scan {
    reset_model; cell parent WRAPPER; cell parent/leaf LUT1
    set_property DONT_TOUCH true parent
    check {[hf2::cell_protection_name parent/leaf] eq "EXISTING_CELL_DONT_TOUCH"} "Ancestor outside candidate list lost"
    set_property DONT_TOUCH false parent
    hf2::scan $out/refresh_one
    check {[hf2::cell_protection_name parent/leaf] eq ""} "New scan retained stale protection"
    set_property ASYNC_REG true parent/leaf
    hf2::scan $out/refresh_two
    check {[hf2::cell_protection_name parent/leaf] eq "ASYNC_REG"} "Newly protected cell omitted"
}
case selector_rejects_stale_classification_inventory {
    reset_model; set item [fixture 110]
    dict set item sink_kinds invalid/D ORDINARY
    check {[catch {hf2::select_sinks $item 0} detail]} "Stale classification accepted"
    check {$detail eq "STALE_SINK_KIND_INVENTORY"} "Wrong stale inventory diagnosis"
}
case upstream_port_and_undriven_nets_do_not_query_empty_objects {
    reset_model; cell sink FDRE; pin sink/D IN; link external {sink/D}
    rename get_cells model_get_cells
    proc get_cells {args} {
        if {[lsearch -exact $args -of_objects]>=0 && [option $args -of_objects] eq ""} {
            error "Empty native object collection"
        }
        return [model_get_cells {*}$args]
    }
    set items [hf2::discover $out/undriven 0 external 1]
    check {![llength $items]} "Undriven net became eligible"
    set f [open $out/undriven/high_fanout.tsv r]; set rows [read $f]; close $f
    check {[string match *UNSUPPORTED_DRIVER_COUNT* $rows]} "Undriven evidence omitted"
    rename get_ports model_get_ports
    proc get_ports {args} {return input_port}
    set items [hf2::discover $out/port_driver 0 external 1]
    check {[llength $items]==1 && [dict get [lindex $items 0] driver_name] eq "input_port"} "Input port driver omitted"
    check {[dict get [lindex $items 0] ref] eq ""} "Port misclassified as primitive"
    rename get_cells {}; rename model_get_cells get_cells
    rename get_ports {}; rename model_get_ports get_ports
}
case array_location_cache_refreshes_and_discards_removed_cells {
    reset_model; cell a FDRE SLICE_X1Y1
    hf2::saved_placement_cache
    check {[hf2::site_key a/D] eq "SLICE_X1Y1"} "Initial location missing"
    dict set ::cells a LOC SLICE_X2Y2
    set ::hf2::placement_cache_ready 0
    hf2::saved_placement_cache
    check {[hf2::site_key a/D] eq "SLICE_X2Y2"} "Location refresh stale"
    dict unset ::cells a
    set ::hf2::placement_cache_ready 0
    hf2::saved_placement_cache
    check {![info exists ::hf2::locations(a)]} "Removed cell retained in refreshed index"
}
case macro_internal_sink_remains_connected_and_consumes_root_budget {
    reset_model; set item [fixture 110]
    dict set ::cells s0 PRIMITIVE_LEVEL INTERNAL
    lassign [hf2::select_sinks $item 0] move keep why
    check {$keep eq "s0/D" && [dict get $why MACRO_INTERNAL_CELL]==1} "Macro internal pin not retained"
    hf2::apply_memory [list $item] $out/macro_internal
    check {[dict get $::pins s0/D NET] eq "original"} "Macro internal wire changed"
    check {[llength [f96::loads source/Q]]<=96} "Retained macro branch omitted from budget"
    foreach p [dict get $item sinks] {check {[source_of $p] eq "source/Q"} "Macro protection changed function"}
}
puts "PASS: $count connectivity/legality groups; native execution NOT_RUN"
