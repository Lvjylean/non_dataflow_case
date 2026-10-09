# Candidate connections are a bounded view of this capture, in this read epoch.
# Configuration/STA and every uncertain relationship retain native reads.
namespace eval locality_inventory {
    variable connection_epoch {}
    variable connection_cells; array set connection_cells {}
    variable connection_nets; array set connection_nets {}
    variable connection_cell_order {}; variable connection_net_order {}
    variable connection_byte_limit 134217728
    variable connection_clockless; array set connection_clockless {}
    variable connection_counters {}; variable connection_started 0
}
proc locality_inventory::input_mode {} {
    set mode enabled
    if {[info exists ::env(BL_INPUT_REUSE_MODE)]} {set mode $::env(BL_INPUT_REUSE_MODE)}
    if {$mode ni {enabled reference}} {error "Unknown candidate input reuse mode: $mode"}
    return $mode
}
proc locality_inventory::connection_reset {} {
    variable connection_epoch;variable connection_clockless
    variable connection_cells;variable connection_nets
    variable connection_cell_order;variable connection_net_order
    variable connection_counters;variable connection_started
    set connection_epoch {};array unset connection_clockless *
    array unset connection_cells *;array unset connection_nets *
    set connection_cell_order {};set connection_net_order {}
    set connection_started [clock microseconds]
    set connection_counters [dict create mode [input_mode] snapshot_cells 0 snapshot_nets 0 \
        cell_metadata_hits 0 input_cell_hits 0 input_cell_fallbacks 0 signal_hits 0 signal_fallbacks 0 \
        load_hits 0 load_fallbacks 0 config_hits 0 config_fallbacks 0 fixed_route_hits 0 \
        clock_validation_net_calls 0 clock_validation_name_calls 0 clock_validation_clock_calls 0 \
        clock_validation_elapsed_us 0 clock_validation_fallback_nets 0]
}
proc locality_inventory::connection_count {key {amount 1}} {
    variable connection_counters
    if {$connection_counters eq ""} {connection_reset}
    dict incr connection_counters $key $amount
}
proc locality_inventory::connection_readable {} {
    variable shared_active;variable connection_epoch;variable capture_epoch
    if {!$shared_active || $connection_epoch eq ""} {return 0}
    if {![info exists ::vs::active] || !$::vs::active} {return 0}
    vs::assert_readable
    return [expr {$connection_epoch eq $::vs::epoch && $capture_epoch eq $::vs::epoch}]
}
proc locality_inventory::connection_install {snapshot} {
    # Deserialization is the only full-map dict operation. Native Vivado can
    # reparse large dict arguments on every lookup; hot reads use local arrays.
    variable connection_cells;variable connection_nets
    variable connection_cell_order;variable connection_net_order
    array unset connection_cells *;array unset connection_nets *
    set cell_map [dict get $snapshot cells]
    set net_map [dict get $snapshot nets]
    if {[dict size $cell_map]>65536} {error snapshot_cell_budget}
    set connection_cell_order [dict keys $cell_map]
    set connection_net_order [dict keys $net_map]
    array set connection_cells $cell_map
    array set connection_nets $net_map
    set load_count 0
    foreach key $connection_net_order {
        set item $connection_nets($key)
        incr load_count [llength [dict get $item before]]
        if {$load_count>262144} {error snapshot_load_budget}
        # Preserve exactly the reference receiver ordering and de-duplication.
        dict set item before [lsort -unique [dict get $item before]]
        set connection_nets($key) $item
    }
}
proc locality_inventory::connection_load {folder} {
    variable shared_active;variable capture_epoch;variable capture_folder
    variable connection_epoch;variable connection_clockless
    variable connection_cells;variable connection_nets
    variable connection_cell_order;variable connection_net_order
    connection_reset
    if {[input_mode] eq "reference" || !$shared_active || [file normalize $folder] ne $capture_folder} {return 0}
    vs::assert_readable
    set path $folder/input_snapshot.tcl
    if {![file exists $path] || [file size $path]>$::locality_inventory::connection_byte_limit} {return 0}
    if {[catch {
        source $path
        if {[dict get $locality_reuse_snapshot schema] ne "targeted-native-input-v1" || \
            [dict get $locality_reuse_snapshot epoch] ne $capture_epoch || $capture_epoch ne $::vs::epoch} {error snapshot_epoch_mismatch}
        connection_install $locality_reuse_snapshot
    } why]} {
        array unset connection_cells *;array unset connection_nets *
        set connection_cell_order {};set connection_net_order {}
        dict set ::locality_inventory::connection_counters snapshot_unavailable $why
        return 0
    }
    unset locality_reuse_snapshot
    set connection_epoch $capture_epoch
    dict set ::locality_inventory::connection_counters snapshot_cells [array size connection_cells]
    dict set ::locality_inventory::connection_counters snapshot_nets [array size connection_nets]
    # Keep original per-cell input collection order in ji::record. Resolve the
    # targeted cell handles in batches, rather than a lookup for every record.
    set cell_names $connection_cell_order
    foreach key $connection_net_order {lappend cell_names [file dirname $key]}
    foreach batch [sb::name_chunks [lsort -unique $cell_names] 512] {
        if {[catch {
            connection_count cell_lookup_batch_calls
            set objects [get_cells -quiet $batch]
            connection_count cell_lookup_name_calls
            set names [sb::names $objects cell]
            if {[lsort $names] ne [lsort $batch]} {error missing_snapshot_cell_objects}
        } why]} {connection_count cell_lookup_fallback_batches;continue}
        foreach object $objects name $names {set ::sb::cell_objects($name) $object}
    }
    # IS_CLOCK incidence identifies actual clock pins, but get_clocks can also
    # attach a generated clock to a data net. Prove the entire bounded batch is
    # clockless with one native read; any nonempty/unknown result falls back.
    array set roots {};set root_order {}
    foreach key $connection_net_order {
        set root [dict get $connection_nets($key) root]
        if {![info exists roots($root)]} {lappend root_order $root}
        lappend roots($root) $key
    }
    foreach batch [sb::name_chunks $root_order 512] {
        set tick [clock microseconds]
        set safe 0
        if {![catch {
            connection_count clock_validation_net_calls
            set objects [get_nets -quiet $batch]
            connection_count clock_validation_name_calls
            if {[lsort [sb::names $objects net]] ne [lsort $batch]} {error missing_snapshot_net_objects}
            connection_count clock_validation_clock_calls
            set clocks [get_clocks -quiet -of_objects $objects]
            set safe [expr {![llength $clocks]}]
        } why] && $safe} {
            foreach root $batch {foreach key $roots($root) {set connection_clockless($key) 1}}
        } else {
            foreach root $batch {connection_count clock_validation_fallback_nets [llength $roots($root)]}
        }
        connection_count clock_validation_elapsed_us [expr {[clock microseconds]-$tick}]
    }
    return 1
}
proc locality_inventory::connection_signal {pin} {
    variable connection_cells;variable connection_nets;variable connection_clockless
    if {![connection_readable]} {return {}}
    set cell [file dirname $pin];set port [file tail $pin]
    # All FF clock connections and supply-on-C cases are queried natively.
    # A nonclock descriptor set never certifies that an actual C pin is absent.
    if {$port eq "C"} {return {}}
    if {![info exists connection_cells($cell)] || ![dict exists $connection_cells($cell) $port]} {return {}}
    set item [dict get $connection_cells($cell) $port]
    set kind [dict get $item kind];set raw [dict get $item value]
    if {$kind in {constant clock}} {
        if {$kind eq "constant" && $raw ni {POWER GROUND}} {return {}}
        if {$kind eq "clock" && $port ne "C"} {return {}}
        set signal [list $kind $raw]
        return [dict create key $signal kind $kind anchor $pin slr "" signal $signal]
    }
    if {$kind ne "ordinary"} {return {}}
    if {![info exists connection_clockless($raw)] || ![info exists connection_nets($raw)]} {return {}}
    set source [file dirname $raw]
    set metadata [cell_metadata $source]
    if {$metadata eq "" || [rf::known_protected_ip $raw] || ![lb::input_source [dict get $metadata ref] [file tail $raw]]} {return {}}
    return [dict create key $raw kind ordinary anchor $raw slr [dict get $metadata slr] signal [list drivers [list $raw]]]
}
proc locality_inventory::connection_inputs {name pin_names} {
    variable connection_cells
    if {![connection_readable] || ![info exists connection_cells($name)]} {connection_count input_cell_fallbacks;return {}}
    set metadata [cell_metadata $name]
    if {$metadata ne "" && [dict get $metadata ref] in {FDRE FDSE}} {
        # The FF view certifies only nonclock inputs. Even an unexpectedly
        # absent C pin cannot turn that view into a complete FF pin inventory.
        connection_count input_cell_fallbacks
        return {}
    }
    set captured $connection_cells($name)
    set expected {};foreach pin [dict keys $captured] {lappend expected $name/$pin}
    if {[lsort $pin_names] ne [lsort $expected]} {connection_count input_cell_fallbacks;return {}}
    set result {}
    foreach fullpin $pin_names {
        set pin [file tail $fullpin]
        set sig [connection_signal $fullpin]
        if {$sig eq ""} {connection_count input_cell_fallbacks;return {}}
        dict set result $pin $sig
    }
    connection_count input_cell_hits
    return $result
}
proc locality_inventory::connection_net {key} {
    variable connection_cells;variable connection_nets;variable connection_clockless
    if {![connection_readable] || ![info exists connection_clockless($key)] || ![info exists connection_nets($key)]} {return {}}
    set metadata [cell_metadata [file dirname $key]]
    if {$metadata eq ""} {return {}}
    return [dict create key $key kind ordinary anchor $key slr [dict get $metadata slr] \
        signal [list drivers [list $key]] before [dict get $connection_nets($key) before]]
}
proc locality_inventory::connection_config {name} {
    variable rows
    if {![connection_readable] || ![info exists rows($name)]} {return {}}
    lassign $rows($name) ref loc init
    if {![regexp {^LUT[1-6]$} $ref] || $init eq ""} {return {}}
    return [dict create INIT [string tolower $init]]
}
proc locality_inventory::connection_fixed_safe {name} {
    variable reasons
    if {![connection_readable] || ![info exists reasons($name)] || [llength $reasons($name)]} {return 0}
    if {[connection_net $name/O] eq ""} {return 0}
    connection_count fixed_route_hits
    return 1
}
proc locality_inventory::connection_save {path} {
    variable connection_counters;variable connection_started
    if {$connection_counters eq ""} {return}
    dict set connection_counters elapsed_us [expr {[clock microseconds]-$connection_started}]
    set f [open $path w];puts $f "key\tvalue"
    dict for {key value} $connection_counters {puts $f "$key\t[field $value]"}
    close $f
}
