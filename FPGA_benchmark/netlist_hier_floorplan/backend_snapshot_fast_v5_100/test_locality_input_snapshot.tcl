# Counted native mock: exact complete records, traversal order and lifecycle.
source [file join [file dirname [info script]] code regional core.tcl]
source [file join [file dirname [info script]] code regional regional.tcl]
source [file join [file dirname [info script]] code regional local_broadcast.tcl]
source [file join [file dirname [info script]] code regional locality_inventory.tcl]
array set prop {};array set cellpins {};array set netpins {};array set pinnet {}
array set counts {}
proc count {name} {global counts;if {![info exists counts($name)]} {set counts($name) 0};incr counts($name)}
proc option {args key} {set i [lsearch -exact $args $key];if {$i<0} {return {}};return [lindex $args [expr {$i+1}]]}
proc get_property {key objects} {
    global prop
    count get_property
    set result {};foreach object $objects {
        if {![info exists prop($object,$key)]} {error "Missing mock property:$object:$key"}
        lappend result $prop($object,$key)
    }
    if {[llength $objects]==1} {return [lindex $result 0]};return $result
}
proc get_cells {args} {global cellpins;count get_cells;set result {};foreach name [lindex $args end] {if {[info exists cellpins(c:$name)]} {lappend result c:$name}};return $result}
proc get_nets {args} {
    global pinnet netpins;count get_nets
    set objects [option $args -of_objects];set result {}
    if {$objects ne ""} {foreach object $objects {if {[info exists pinnet($object)]} {lappend result $pinnet($object)}}} \
    else {foreach name [lindex $args end] {if {[info exists netpins($name)]} {lappend result $name} elseif {[info exists netpins(n:$name)]} {lappend result n:$name}}}
    return [lsort -unique $result]
}
proc get_pins {args} {
    global cellpins netpins prop;count get_pins
    set objects [option $args -of_objects];set filter [option $args -filter];set result {}
    if {$objects eq ""} {foreach name [lindex $args end] {if {[info exists prop(p:$name,NAME)]} {lappend result p:$name}};return $result}
    foreach object $objects {
        set pins {};if {[info exists cellpins($object)]} {set pins $cellpins($object)} elseif {[info exists netpins($object)]} {set pins $netpins($object)}
        foreach pin $pins {
            if {[string first {DIRECTION == IN} $filter]>=0 && $prop($pin,DIRECTION) ne "IN"} {continue}
            if {[string first {DIRECTION == OUT} $filter]>=0 && $prop($pin,DIRECTION) ne "OUT"} {continue}
            lappend result $pin
        }
    }
    return $result
}
proc get_ports {args} {count get_ports;return {}}
proc get_clocks {args} {
    global pinnet;count get_clocks
    set objects [option $args -of_objects]
    if {$objects eq ""} {return clock:clk}
    foreach object $objects {if {$object eq "n:clk" || ([info exists pinnet($object)] && $pinnet($object) eq "n:clk")} {return clock:clk}}
    return {}
}
proc get_sites {args} {return site:SLICE_X0Y0}
proc get_slrs {args} {return slr:SLR0}
proc get_clock_regions {args} {return cr:X0Y0}
proc net {name type pins} {
    global prop cellpins netpins pinnet
    set netpins(n:$name) {}
    foreach {key value} [list CLASS net NAME $name TYPE $type IS_ROUTE_FIXED 0 FIXED_ROUTE {}] {set prop(n:$name,$key) $value}
    foreach pin $pins {
        lappend netpins(n:$name) p:$pin;set pinnet(p:$pin) n:$name
    }
}
proc cell {name ref inputs} {
    global prop cellpins
    set cellpins(c:$name) {}
    set init [expr {[string match LUT* $ref] ? "2'H2" : "1'b0"}]
    foreach {key value} [list CLASS cell NAME $name REF_NAME $ref LOC SLICE_X0Y0 BEL {} INIT $init IS_C_INVERTED 0 IS_D_INVERTED 0 IS_R_INVERTED 0 IS_S_INVERTED 0 DONT_TOUCH 0] {set prop(c:$name,$key) $value}
    foreach pin [concat $inputs [list [expr {$ref in {FDRE FDSE} ? "Q" : "O"}]]] {
        set full $name/$pin;lappend cellpins(c:$name) p:$full
        foreach {key value} [list CLASS pin NAME $full DIRECTION [expr {$pin in {O Q} ? "OUT" : "IN"}] IS_CLOCK [expr {$pin eq "C"}]] {set prop(p:$full,$key) $value}
    }
}
foreach {object class name} {clock:clk clock clk site:SLICE_X0Y0 site SLICE_X0Y0 slr:SLR0 slr SLR0 cr:X0Y0 clock_region X0Y0} {set prop($object,CLASS) $class;set prop($object,NAME) $name}
set prop(clock:clk,PERIOD) 6.2
cell src FDRE {CE C R D};cell root FDRE {R CE C D}
cell a LUT1 I0;cell b LUT1 I0;cell mux MUXF7 {S I1 I0}
cell dst FDRE {D C R CE}
net src SIGNAL {src/Q a/I0 b/I0 mux/S root/CE}
net a SIGNAL {a/O mux/I0};net b SIGNAL {b/O mux/I1};net mux SIGNAL {mux/O root/D}
net root SIGNAL {root/Q dst/D};net dst SIGNAL {dst/Q}
net clk SIGNAL {src/C root/C dst/C}
net gnd GROUND {src/D src/R root/R dst/R}
net vcc POWER {src/CE dst/CE}
set out [file join /tmp locality_input_snapshot_mock_[pid]];file mkdir $out
proc check {condition why} {if {!$condition} {error $why}}
proc capture_mock {folder {stale 0} {omit {}}} {
    global prop cellpins netpins
    set ::locality_inventory::capture_epoch $::vs::epoch
    set ::locality_inventory::capture_folder [file normalize $folder]
    set ::locality_inventory::sites(SLICE_X0Y0) {SLR0 0 0}
    set snapshot [dict create schema targeted-native-input-v1 epoch [expr {$::vs::epoch-$stale}] cells {} nets {}]
    foreach object [array names cellpins] {
        set name $prop($object,NAME);set ref $prop($object,REF_NAME)
        set ::locality_inventory::rows($name) [list $ref SLICE_X0Y0 $prop($object,INIT)]
        set ::locality_inventory::reasons($name) {}
        set inputs {}
        foreach pin $cellpins($object) {
            if {$prop($pin,DIRECTION) ne "IN"} {continue}
            set net [lindex [get_nets -of_objects $pin] 0];set type $prop($net,TYPE)
            if {$type in {POWER GROUND}} {set item [dict create kind constant value $type]} \
            elseif {$prop($pin,IS_CLOCK)} {set item [dict create kind clock value $prop($net,NAME)]} \
            else {
                set driver "";foreach p $netpins($net) {if {$prop($p,DIRECTION) eq "OUT"} {set driver $prop($p,NAME)}}
                set item [dict create kind ordinary value $driver]
            }
            dict set inputs [file tail $prop($pin,NAME)] $item
        }
        dict set snapshot cells $name $inputs
    }
    foreach net [array names netpins] {
        if {$net in {n:clk n:gnd n:vcc}} {continue}
        set driver "";set loads {}
        foreach p $netpins($net) {if {$prop($p,DIRECTION) eq "OUT"} {set driver $prop($p,NAME)} else {lappend loads $prop($p,NAME)}}
        dict set snapshot nets $driver [dict create root $prop($net,NAME) before [lsort $loads]]
    }
    if {$omit ne ""} {dict unset snapshot nets $omit}
    set f [open $folder/input_snapshot.tcl w];puts $f [list set locality_reuse_snapshot $snapshot];close $f
}
proc records {mode folder {stale 0} {omit {}}} {
    global counts
    set ::env(BL_INPUT_REUSE_MODE) $mode
    vs::begin candidate_mock
    capture_mock $folder $stale $omit
    locality_inventory::activate;locality_inventory::connection_load $folder
    foreach var {cells inputs nodes nets} {array unset ::ji::$var *}
    array unset counts *
    array set counts {get_cells 0 get_pins 0 get_nets 0 get_property 0 get_clocks 0 get_ports 0}
    foreach name {root src mux a b dst} {ji::record $name}
    set seen {};set active {};ji::expand mux 0 seen active
    set result {}
    foreach var {cells inputs nodes nets} {
        set ordered {};foreach name [lsort [array names ::ji::$var]] {dict set ordered $name [set ::ji::${var}($name)]}
        dict set result $var $ordered
    }
    dict set result traversal [dict keys $seen]
    set measured [array get counts]
    set reuse $::locality_inventory::connection_counters
    vs::end;locality_inventory::deactivate
    return [list $result $measured $reuse]
}
lassign [records reference $out] reference reference_calls reference_reuse
lassign [records enabled $out] fast fast_calls fast_reuse
check [expr {$fast eq $reference}] exact_complete_records
check [expr {[dict get $fast traversal] eq {mux b a}}] native_input_order
check [expr {[dict get $fast_calls get_nets]<[dict get $reference_calls get_nets]}] fewer_native_net_queries
check [expr {[dict get $fast_reuse input_cell_hits]==3}] complete_combination_input_hits
check [expr {[dict get $fast_reuse signal_fallbacks]>=3}] every_ff_clock_native
check [expr {[dict get $fast_reuse config_hits]==2}] same_epoch_lut_init
lassign [records enabled $out 1] stale stale_calls stale_reuse
check [expr {$stale eq $reference}] stale_snapshot_native_fallback
check [expr {[dict get $stale_reuse input_cell_hits]==0}] stale_has_no_input_hit
lassign [records enabled $out 0 src/Q] partial partial_calls partial_reuse
check [expr {$partial eq $reference}] incomplete_signal_native_fallback
check [expr {[dict get $partial_reuse input_cell_fallbacks]>0}] incomplete_counted
check [expr {[dict get $partial_reuse signal_hits]>0 && [dict get $partial_reuse load_hits]>0}] partial_view_retains_safe_hits
# A supply-connected C pin remains a constant according to native sb::signal,
# and the snapshot never substitutes clock semantics for it.
set pinnet(p:src/C) n:gnd
lassign [records reference $out] supply_reference supply_reference_calls supply_reference_reuse
lassign [records enabled $out] supply_fast supply_fast_calls supply_fast_reuse
check [expr {$supply_fast eq $supply_reference}] supply_on_c_native_equivalence
check [expr {[dict get $supply_fast inputs src C signal] eq {constant GROUND}}] supply_on_c_preserved
set pinnet(p:src/C) n:clk
# Generated clocks discovered in the native batch invalidate reuse for those
# ordinary signals without changing their original native rejection behavior.
rename get_clocks get_clocks_original
proc get_clocks {args} {if {[lsearch -exact $args -of_objects]>=0 && [lsearch -exact [option $args -of_objects] n:src]>=0} {count get_clocks;return clock:clk};return [get_clocks_original {*}$args]}
set ::env(BL_INPUT_REUSE_MODE) enabled
vs::begin clock_mock;capture_mock $out;locality_inventory::activate;locality_inventory::connection_load $out
check [expr {[locality_inventory::connection_net src/Q] eq ""}] generated_clock_native_fallback
check [expr {[dict get $::locality_inventory::connection_counters clock_validation_fallback_nets]>0}] generated_clock_counted
vs::end;locality_inventory::deactivate
rename get_clocks {};rename get_clocks_original get_clocks
# No snapshot can be consumed after mutation, place, route or checkpoint reopen.
foreach command {connect_net set_property place_design route_design open_checkpoint} {
    proc ::$command {args} {return}
    vs::begin mutation_mock;capture_mock $out;locality_inventory::activate;locality_inventory::connection_load $out
    set rc [catch {uplevel #0 [list $command]} why]
    check [expr {[dict get $::vs::counters invalidated] eq $command}] mutation_trace_$command
    check [expr {[catch {locality_inventory::connection_net src/Q}]}] invalidated_read_$command
    set ::ji::inputs(cached) {}
    check [expr {[catch {ji::record cached}]}] invalidated_record_$command
    vs::end;locality_inventory::deactivate
    rename ::$command {}
}
vs::begin old_epoch;capture_mock $out;locality_inventory::activate;locality_inventory::connection_load $out;vs::end
set ::ji::cells(src) [dict create name src ref STALE slr SLR9 x 9 y 9 period 99]
set ::ji::inputs(src) stale
vs::begin new_epoch
check [expr {[locality_inventory::connection_net src/Q] eq ""}] new_epoch_cannot_reuse
check [expr {[dict get [ji::describe src] ref] eq "FDRE"}] new_epoch_refreshes_descriptions
check [expr {![info exists ::ji::inputs(src)]}] new_epoch_clears_records
vs::end;locality_inventory::deactivate
check [expr {[array size ::locality_inventory::connection_cells]==0 && [array size ::locality_inventory::connection_nets]==0}] released_array_views
# A rejected import cannot leave part of its array view usable.
vs::begin bad_load_budget
capture_mock $out
set f [open $out/input_snapshot.tcl a]
puts $f {dict set locality_reuse_snapshot nets src/Q before [lrepeat 262145 dst/D]}
close $f
locality_inventory::activate
check [expr {[locality_inventory::connection_load $out]==0}] over_budget_rejected
check [expr {[array size ::locality_inventory::connection_cells]==0 && [array size ::locality_inventory::connection_nets]==0}] rejected_import_clears_arrays
check [expr {[locality_inventory::connection_net src/Q] eq ""}] rejected_import_cannot_reuse
vs::end;locality_inventory::deactivate
file delete -force $out
puts "INPUT_SNAPSHOT_PASS reference_native=$reference_calls optimized_native=$fast_calls reuse=$fast_reuse"
