# Native first-placement FF/LUT replication with pre-placement memory handling.
set hf2_here [file dirname [file normalize [info script]]]
source $hf2_here/../fanout96/core.tcl
source $hf2_here/../fanout96/fast.tcl
source $hf2_here/../fanout96/quick.tcl
namespace eval hf2 {
    variable cfg [dict create native_target 96 memory_target 96 native_mode NONE \
        refinement_passes 1 native_min_target 8 memory_lut_budget 50000 \
        post_place_lut_budget 4096 local_site_attempts 64 upstream_levels 1]
}
source $hf2_here/memory.tcl
source $hf2_here/scan.tcl
source $hf2_here/eco.tcl
unset hf2_here

proc hf2::configure {settings} {
    variable cfg
    dict for {key value} $settings {
        if {![dict exists $cfg $key]} {error "Unknown fanout setting: $key"}
    }
    set next [dict merge $cfg $settings]
    foreach key {native_target memory_target native_min_target} {
        set n [dict get $next $key]
        if {![string is integer -strict $n] || $n < 2 || $n >= 100} {error "Invalid $key: require 2..99"}
    }
    if {[dict get $next native_min_target] > [dict get $next native_target]} {error "Minimum target exceeds initial target"}
    foreach {key low high} {refinement_passes 0 1 memory_lut_budget 1 1000000 post_place_lut_budget 0 1000000 local_site_attempts 1 1024 upstream_levels 0 1} {
        set n [dict get $next $key]
        if {![string is integer -strict $n] || $n < $low || $n > $high} {error "Invalid $key"}
    }
    if {[dict get $next native_mode] ni {NONE SLR CLOCK_REGION MACRO}} {error "Invalid native_mode"}
    set cfg $next
    # The scan is independent of the native physical target. It must see 100.
    set ::f96::target 96
}
proc hf2::truth {value} {expr {[string tolower $value] in {1 true yes}}}
proc hf2::ff_count {} {llength [get_cells -hier -filter {IS_PRIMITIVE == 1 && REF_NAME =~ FD*}]}
proc hf2::classify {ref name} {
    if {[string match f96_identity_* $name]} {return OWNED_IDENTITY}
    if {[regexp {^(FD|FDCE|FDPE|FDRE|FDSE|LUT[1-6]|LUT6_2)$} $ref]} {return NATIVE}
    if {[regexp {^(RAMB(18|36)(E[12])?|URAM288(_BASE)?)$} $ref]} {return MEMORY_IDENTITY}
    # True clocks have already been excluded by the complete electrical scan.
    if {$ref eq "" || [regexp {^(BUFG|BUFGCE|BUFGCTRL|BUFGCE_DIV|IBUF)$} $ref]} {return OTHER_IDENTITY}
    if {$ref in {CARRY4 CARRY8}} {return CARRY_IDENTITY}
    return UNSUPPORTED
}
proc hf2::flag {object key} {
    if {[catch {get_property $key $object} value]} {return 0}
    return [truth $value]
}
proc hf2::cell_protection {cell {allow_owned 0}} {
    return [cell_protection_name [get_property NAME $cell] $allow_owned]
}
proc hf2::ensure_protection_snapshot {} {
    variable protection_snapshot_ready; variable protection_self; variable internal_cells
    if {$protection_snapshot_ready} {return}
    set protection_self [dict create]
    # A complete sparse snapshot also covers protected ancestors outside the
    # selected sinks. Retaining millions of negative per-cell entries is costly.
    set cells [get_cells -hier -quiet -filter {DONT_TOUCH == 1 || ASYNC_REG == 1}]
    foreach name [plain_values NAME $cells] dt [plain_values DONT_TOUCH $cells] ar [plain_values ASYNC_REG $cells] {
        if {[truth $ar]} {dict set protection_self $name ASYNC_REG} elseif {[truth $dt]} {dict set protection_self $name EXISTING_CELL_DONT_TOUCH}
    }
    array unset internal_cells; array set internal_cells {}
    foreach name [plain_values NAME [get_cells -hier -quiet -filter {PRIMITIVE_LEVEL == INTERNAL}]] {
        set internal_cells($name) 1
    }
    set protection_snapshot_ready 1
}
proc hf2::cell_protection_name {name {allow_owned 0}} {
    variable protection_self; variable internal_cells
    if {$name eq "" || ($allow_owned && [string match f96_identity_* $name])} {return ""}
    ensure_protection_snapshot
    # Macro-internal leaf pins are visible electrically but cannot be rewired.
    if {[info exists internal_cells($name)]} {return MACRO_INTERNAL_CELL}
    while {$name ne ""} {
        if {[dict exists $protection_self $name]} {return [dict get $protection_self $name]}
        set slash [string last / $name]
        if {$slash < 0} {break}
        set name [string range $name 0 [expr {$slash-1}]]
    }
    return ""
}
proc hf2::prime_protection {items} {ensure_protection_snapshot}
proc hf2::protection_reason {item action} {
    set driver [dict get $item driver]
    foreach net [get_nets -quiet -segments -of_objects $driver] {
        if {[flag $net DONT_TOUCH]} {return EXISTING_NET_DONT_TOUCH}
    }
    if {[dict get $item ref] ne ""} {
        set cell [get_cells -quiet -of_objects $driver]
        set reason [cell_protection $cell [expr {$action eq "OWNED_IDENTITY"}]]
        if {$reason ne ""} {return $reason}
        if {$action eq "NATIVE"} {
            set inputs [get_pins -quiet -of_objects $cell -filter {DIRECTION == IN}]
            foreach net [get_nets -quiet -segments -of_objects $inputs] {
                if {[flag $net DONT_TOUCH]} {return EXISTING_INPUT_NET_DONT_TOUCH}
            }
        }
    }
    if {$action ne "NATIVE" && [string match */inst/i_synth/* [dict get $item driver_name]]} {
        return PROTECTED_IP_MANUAL_EDIT
    }
    return ""
}
proc hf2::actions {items out} {
    file mkdir $out
    set native {}; set memory {}; set other {}
    set f [open $out/actions.tsv w]
    puts $f "driver\tref\tlogical\taction\treason"
    foreach item $items {
        set name [dict get $item driver_name]
        set cellname [string range $name 0 [expr {[string last / $name]-1}]]
        set action [classify [dict get $item ref] $cellname]; set reason ""
        if {$action eq "NATIVE" && [dict exists $item keep_sinks] && [llength [dict get $item keep_sinks]]} {set action MIXED_IDENTITY}
        if {$action ne "UNSUPPORTED"} {set reason [protection_reason $item $action]}
        if {$reason ne ""} {set action BLOCKED_PROTECTION}
        switch $action {
            NATIVE {lappend native $item}
            MEMORY_IDENTITY {lappend memory $item}
            OTHER_IDENTITY - CARRY_IDENTITY - MIXED_IDENTITY - OWNED_IDENTITY {lappend other $item}
        }
        puts $f "$name\t[dict get $item ref]\t[llength [dict get $item sinks]]\t$action\t$reason"
    }
    close $f
    return [list $native $memory $other]
}
proc hf2::mark_native {items target out} {
    variable cfg
    file mkdir $out
    set names {}
    set f [open $out/native_requests.tsv w]
    puts $f "driver\tnet\tphysical_target\tmode\tpblock\tstatus\tdetail"
    foreach item $items {
        set driver_name [dict get $item driver_name]
        set pin [get_pins -quiet [list $driver_name]]
        if {[llength $pin] != 1 || [get_property NAME $pin] ne $driver_name} {
            error "Native driver is stale or ambiguous: $driver_name"
        }
        set net [get_nets -quiet -of_objects $pin]
        if {[llength $net] != 1} {error "Expected one direct native output net"}
        set name [get_property NAME $net]
        set mode [dict get $cfg native_mode]
        set rc [catch {
            set_property FORCE_MAX_FANOUT $target $net
            if {$mode ne "NONE"} {set_property MAX_FANOUT_MODE $mode $net}
            if {[get_property FORCE_MAX_FANOUT $net] != $target} {error "Physical target was not retained"}
            if {$mode ne "NONE" && [get_property MAX_FANOUT_MODE $net] ne $mode} {error "Native grouping mode was not retained"}
        } detail]
        set status [expr {$rc ? "REQUEST_REJECTED" : "PROPERTY_SET_RESULT_PENDING"}]
        if {!$rc} {lappend names $name}
        set pb [get_property PBLOCK [get_cells -of_objects $pin]]
        puts $f "$driver_name\t$name\t$target\t$mode\t$pb\t$status\t[string map [list \n { } \t { }] $detail]"
    }
    close $f
    return $names
}
proc hf2::acceptance_from_rows {rows} {
    set violations 0; set exceptions 0
    foreach row $rows {
        set status [dict get $row status]
        set logical [dict get $row logical]
        if {$status in {CONSTANT CLOCK_PIN_ONLY} || ($status eq "CLOCK_DISTRIBUTION" && ![string is integer -strict $logical])} {incr exceptions; continue}
        if {[dict get $row logical] >= 100} {incr violations}
    }
    return [dict create status [expr {$violations ? "ANNOTATED_UNMET" : "PASS"}] \
        ordinary_ge100 $violations excluded_clock_or_constant $exceptions]
}
proc hf2::mark_upstream {native out} {
    variable cfg
    if {![dict get $cfg upstream_levels] || ![llength $native]} {return}
    set pins {}; foreach item $native {lappend pins [dict get $item driver_name]}
    set cells [get_cells -quiet -of_objects [get_pins $pins]]
    set inputs [get_pins -quiet -of_objects $cells -filter {DIRECTION == IN && IS_CLOCK == 0}]
    set nets [get_nets -quiet -segments -top_net_of_hierarchical_group -of_objects $inputs]
    set items [discover $out/upstream_scan 0 $nets 1]
    lassign [actions $items $out/upstream_actions] eligible memory other
    mark_native $eligible [dict get $cfg native_target] $out/upstream_native
}
proc hf2::refine {out {placed_items __SCAN__}} {
    variable cfg
    # One optional native pass. There is no iterative target halving.
    if {$placed_items eq "__SCAN__"} {set placed_items [scan $out/refinement_1]}
    set items [f96::required $placed_items]
    lassign [actions $items $out/refinement_actions_1] native memory other
    set f [open $out/refinement.tsv w]
    puts $f "pass\tphysical_target\trequested_nets\treturn_code\tdetail"
    set stop no_eligible_native_targets
    if {![dict get $cfg refinement_passes]} {set stop disabled} elseif {[llength $native]} {
        set target [dict get $cfg native_target]
        set nets [mark_native $native $target $out/native_1]
        if {[llength $nets]} {
            set rc [catch {phys_opt_design -force_replication_on_nets [get_nets $nets]} detail]
            puts $f "1\t$target\t[llength $nets]\t$rc\t[string map [list \n { } \t { }] $detail]"
            set stop [expr {$rc ? "native_command_rejected" : "single_pass_complete"}]
        } else {set stop all_native_requests_rejected}
    }
    close $f
    set f [open $out/refinement_stop.txt w]; puts $f $stop; close $f
}
proc hf2::implement {out} {
    variable cfg
    set ::f96::serial 0; set ::f96::created 0
    set ::hf2::post_helpers 0; set ::hf2::placement_cache_ready 0
    array unset ::hf2::locations; array set ::hf2::locations {}
    set ::hf2::identity_manifest $out/identity_manifest.tsv
    set f [open $::hf2::identity_manifest w]; puts $f "cell\troot\tstage"; close $f
    set initial [scan $out/before]
    lassign [actions $initial $out/actions] native memory other
    apply_memory [concat $memory $other] $out/memory_patch
    set current [scan $out/pre_place]
    lassign [actions $current $out/pre_place_actions] native memory other
    mark_native $native [dict get $cfg native_target] $out/pre_place_native
    mark_upstream $native $out
    audit_identities $out/pre_place
    f96::phase native_first_place
    place_design
    set placed_items [scan $out/post_place]
    f96::phase native_phys_opt
    refine $out $placed_items
    # One final, bounded ECO batch covers new native generations and non-native
    # drivers. Only the new helpers are locally placed; no second place_design.
    write_checkpoint $out/post_native.dcp
    set residual [f96::required [scan $out/post_native]]
    apply_residual $residual $out/residual_patch
    set final [scan $out/pre_route]
    actions $final $out/final_actions
    audit_identities $out/pre_route
    assert_placed_helpers
    f96::phase fanout_end
    f96::phase route
    route_design
    scan $out/post_route/fanout 1
    audit_identities $out/post_route
}
