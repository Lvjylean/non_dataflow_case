# Read-only, immutable locality inventory.  No timing queries or ECO commands.
# Source core.tcl and regional.tcl first.  Native handles remain in this process;
# the host planners consume only the streamed TSV files returned by capture.
namespace eval locality_inventory {
    variable rows; variable reasons; variable sites
    variable parent_protection; array set parent_protection {}
    variable protection_queries 0; variable protection_native_us 0
    array set rows {}; array set reasons {}; array set sites {}
}
proc locality_inventory::supported {ref} {
    return [regexp {^(LUT[1-6]|MUXF[789]|FDRE|FDSE|RAMB(18|36)E[12]|URAM288(_BASE)?)$} $ref]
}
proc locality_inventory::field {value} {
    if {[regexp {[\t\r\n]} $value]} {error "Locality inventory cannot serialize a tab/newline in an object name or property"}
    return $value
}
proc locality_inventory::block {name reason} {
    variable reasons
    if {![info exists reasons($name)]} {set reasons($name) {}}
    if {[lsearch -exact $reasons($name) $reason]<0} {lappend reasons($name) $reason}
}
proc locality_inventory::clock_pin {name ref} {
    set pin [file tail $name]
    if {[regexp {^FD} $ref]} {return [expr {$pin eq "C"}]}
    if {[regexp {^(RAMB|URAM)} $ref]} {return [regexp {^(CLK|CLKARDCLK|CLKBWRCLK|CLKA|CLKB)$} $pin]}
    return 0
}
proc locality_inventory::reset_protection {} {
    variable parent_protection; variable protection_queries; variable protection_native_us
    array unset parent_protection *
    array unset ::rf::ancestor_cache *
    set protection_queries 0;set protection_native_us 0
}
proc locality_inventory::protected_ancestor {cell} {
    # The original helper cached the answer for each child, but still reread
    # DONT_TOUCH on the same immediate parent for every sibling. Cache only
    # that immutable native parent value within this capture. The result still
    # excludes the queried cell itself and returns the nearest protected parent.
    variable parent_protection;variable protection_queries;variable protection_native_us
    if {[info exists ::rf::ancestor_cache($cell)]} {return $::rf::ancestor_cache($cell)}
    set parent [file dirname $cell];set result ""
    if {$parent ni {. / {}}} {
        if {![info exists parent_protection($parent)]} {
            set tick [clock microseconds]
            # Missing or ambiguous parents retain sb::cell's fail-closed error.
            set value [get_property DONT_TOUCH [sb::cell $parent]]
            incr protection_native_us [expr {[clock microseconds]-$tick}]
            incr protection_queries
            set parent_protection($parent) [sb::one_bit $value]
        }
        if {$parent_protection($parent)} {set result $parent} else {set result [protected_ancestor $parent]}
    }
    set ::rf::ancestor_cache($cell) $result
    return $result
}
proc locality_inventory::runtime_row {stream phase started work {overlap 0}} {
    set elapsed [expr {[clock microseconds]-$started}]
    puts $stream [join [list $phase $elapsed $work $overlap] \t];flush $stream
    puts "LOCALITY_RUNTIME [clock seconds] phase=$phase elapsed_us=$elapsed work=$work overlap=$overlap"
    flush stdout
}
proc locality_inventory::capture {out} {
    variable rows; variable reasons; variable sites
    foreach name {rows reasons sites} {array unset $name *}
    # Ancestor protection is stage-specific.  Do not carry a previous edit's
    # cached answer into this immutable snapshot.
    reset_protection
    file mkdir $out
    set started [clock milliseconds]
    set runtime [open $out/runtime.tsv.tmp w]
    puts $runtime "phase\telapsed_us\twork_units\toverlaps_other_phase"
    set phase_tick [clock microseconds]
    set diag [open $out/diagnostics.tsv.tmp w]
    puts $diag "kind\tobject\tdetail"
    array set used_sites {}; array set all_refs {}
    set cells [get_cells -quiet -hier -filter {IS_PRIMITIVE == 1}]
    # Property vectors are read once per bounded batch, including unsupported
    # primitives: a boundary's missing metadata must never look like no load.
    foreach batch [sb::chunks $cells 512] {
        set names [sb::names $batch]
        set refs [sb::values REF_NAME $batch]
        set locs [sb::values LOC $batch]
        set luts {};set ffs {}
        foreach obj $batch name $names ref $refs loc $locs {
            field $name;field $ref;field $loc
            set rows($name) [list $ref $loc ""]
            set all_refs($name) $ref
            set reasons($name) {}
            if {$loc ne ""} {set used_sites($loc) 1}
            if {![supported $ref]} {block $name unsupported_primitive;continue}
            if {[rf::known_protected_ip $name]} {block $name protected_ip}
            if {[protected_ancestor $name] ne ""} {block $name protected_hierarchy}
            if {$loc eq ""} {block $name unplaced}
            if {[regexp {^LUT[1-6]$} $ref]} {lappend luts $obj}
            if {$ref in {FDRE FDSE}} {lappend ffs $obj}
        }
        set initializable [concat $luts $ffs]
        foreach name [sb::names $initializable] init [sb::values INIT $initializable] {
            field $init;lset rows($name) 2 $init
            if {$init eq ""} {block $name missing_init}
        }
        foreach name [sb::names $ffs] async [sb::values ASYNC_REG $ffs] {
            if {[sb::one_bit $async]} {block $name asynchronous_register}
        }
    }
    runtime_row $runtime cells_and_protection $phase_tick [llength $cells]
    variable protection_queries;variable protection_native_us
    puts $runtime [join [list protection_native_queries $protection_native_us $protection_queries 1] \t];flush $runtime
    unset cells
    set phase_tick [clock microseconds]
    # Invert CR -> sites once, instead of querying CR/SLR for every placed cell.
    # This is bounded by the device's CR count; only occupied sites are retained.
    foreach slr [get_slrs -quiet] {
        set slrname [get_property NAME $slr]
        foreach cr [get_clock_regions -quiet -of_objects $slr] {
            set crname [get_property NAME $cr]
            if {![regexp {^X([0-9]+)Y([0-9]+)$} $crname unused x y]} {
                error "Unexpected clock-region name in locality inventory: $crname"
            }
            foreach site [sb::names [get_sites -quiet -of_objects $cr]] {
                if {![info exists used_sites($site)]} {continue}
                if {[info exists sites($site)] && $sites($site) ne [list $slrname $x $y]} {
                    error "Ambiguous site region in locality inventory: $site"
                }
                set sites($site) [list $slrname $x $y]
            }
        }
    }
    runtime_row $runtime region_cache $phase_tick [array size sites]
    unset used_sites
    set phase_tick [clock microseconds]
    set edges [open $out/edges.tsv.tmp w];puts $edges "driver\tsink"
    # Canonical hierarchical groups are visited exactly once.  For each group,
    # one leaf-pin query provides both drivers and ALL receiving pins, including
    # unsupported barriers.  No fanout threshold or placement-timing selection.
    set all_nets [get_nets -quiet -hier]
    array set fixed_segments {}
    foreach batch [sb::chunks $all_nets 2048] {
        foreach obj $batch fixed [sb::values IS_ROUTE_FIXED $batch] route [sb::values FIXED_ROUTE $batch] {
            if {[sb::one_bit $fixed] || [rf::has_fixed_route $route]} {set fixed_segments($obj) 1}
        }
    }
    runtime_row $runtime fixed_route_inventory $phase_tick [llength $all_nets]
    set phase_tick [clock microseconds]
    set roots [lsort -unique [sb::names [get_nets -quiet -segments -top_net_of_hierarchical_group $all_nets]]]
    unset all_nets
    set clock_roots [get_nets -quiet -segments -top_net_of_hierarchical_group -of_objects \
        [get_pins -quiet -hier -filter {IS_LEAF == 1 && IS_CLOCK == 1}]]
    array set clocks {};foreach name [sb::names $clock_roots] {set clocks($name) 1}
    unset clock_roots
    # Port incidence is much smaller than the netlist.  Resolve each port once
    # instead of making a native get_ports call on every ordinary internal net.
    array set net_ports {};array set port_directions {}
    foreach port [get_ports -quiet *] {
        set name [field [get_property NAME $port]]
        set port_directions($name) [get_property DIRECTION $port]
        foreach root [sb::names [get_nets -quiet -segments -top_net_of_hierarchical_group -of_objects $port]] {
            lappend net_ports($root) $name
        }
    }
    runtime_row $runtime canonical_clocks_ports $phase_tick [llength $roots]
    set phase_tick [clock microseconds]
    array set seen_driver {};array set connected_inputs {}
    set count 0;set edge_count 0;set constant_edges 0
    set diagnostic_count 0;set clock_count 0;set fixed_count 0
    foreach root_batch [sb::chunks $roots 2048] {
      set root_objects [get_nets -quiet $root_batch]
      sb::require [expr {[llength $root_objects]==[llength $root_batch]}] "Missing canonical locality net batch"
      foreach net $root_objects root [sb::names $root_objects] type [sb::values TYPE $root_objects] {
        incr count
        if {$count % 4096 == 1} {
            puts "LOCALITY_INVENTORY [clock seconds] nets=$count/[llength $roots] edges=$edge_count"
            flush stdout;flush $edges;flush $diag
        }
        set segments [get_nets -quiet -segments $net]
        set pins [get_pins -quiet -of_objects $segments -filter {IS_LEAF == 1 && (DIRECTION == OUT || IS_CLOCK == 0)}]
        set drivers {};set sinks {};set other_pins {};set semantic_clocks {}
        foreach pin [sb::names $pins] direction [sb::values DIRECTION $pins] {
            field $pin
            set cell [file dirname $pin]
            if {![info exists all_refs($cell)]} {
                # E.g. an opaque primitive's internal pin.  Preserve it as a
                # barrier instead of silently removing it from the fanout.
                set all_refs($cell) UNKNOWN;set rows($cell) [list UNKNOWN "" ""]
                block $cell unknown_pin_cell
            }
            if {$direction eq "OUT"} {lappend drivers $pin} \
            elseif {$direction eq "IN"} {
                if {[clock_pin $pin $all_refs($cell)]} {
                    lappend semantic_clocks $pin
                } else {lappend sinks $pin;set connected_inputs($pin) 1}
            } else {lappend other_pins $pin;lappend sinks $pin;set connected_inputs($pin) 1;block $cell ambiguous_pin_direction}
        }
        unset pins
        set drivers [lsort -unique $drivers];set sinks [lsort -unique $sinks]
        set ports {};if {[info exists net_ports($root)]} {set ports [lsort -unique $net_ports($root)]}
        if {$type in {POWER GROUND}} {
            foreach sink $sinks {puts $edges "constant $type\t$sink";incr edge_count;incr constant_edges}
            continue
        }
        if {[info exists clocks($root)] || [llength $semantic_clocks]} {
            incr clock_count
            if {![llength $sinks]} {continue}
            # Clock-as-data is an explicit, non-editable boundary.  C and RAM
            # clock pins themselves are deliberately absent; lb::describe_signal
            # will still capture the selected FF's exact clock configuration.
            set key "barrier CLOCK:$root"
            foreach sink $sinks {puts $edges "$key\t$sink";incr edge_count;block [file dirname $sink] clock_used_as_data}
            foreach driver $drivers {block [file dirname $driver] clock_driver}
            puts $diag "clock_as_data\t[field $root]\t[llength $sinks]";incr diagnostic_count
            continue
        }
        set fixed 0
        foreach segment $segments {if {[info exists fixed_segments($segment)]} {set fixed 1;break}}
        set status {}
        set external_input [expr {![llength $drivers] && [llength $ports]==1 && $port_directions([lindex $ports 0]) eq "IN"}]
        if {[llength $drivers]!=1 && !$external_input} {lappend status ambiguous_driver_count}
        if {[llength $ports]} {lappend status port_boundary}
        if {[llength $other_pins]} {lappend status ambiguous_pin_direction}
        if {$fixed} {lappend status fixed_route;incr fixed_count}
        if {[llength $status]} {
            foreach driver $drivers {foreach reason $status {block [file dirname $driver] $reason}}
            # A copy would add a load to its input net, so fixed or ambiguous
            # inputs also make the receiving primitive unavailable for copying.
            foreach sink $sinks {foreach reason $status {block [file dirname $sink] $reason}}
            puts $diag "net_barrier\t[field $root]\t[join $status ,]";incr diagnostic_count
        }
        if {![llength $drivers]} {
            set key [expr {[llength $ports] ? "barrier PORT:[join $ports ,]" : "barrier UNDRIVEN:$root"}]
            foreach sink $sinks {puts $edges "$key\t$sink";incr edge_count}
        } else {
            foreach driver $drivers {
                if {[info exists seen_driver($driver)] && $seen_driver($driver) ne $root} {
                    error "Driver occurs in distinct canonical locality nets: $driver"
                }
                set seen_driver($driver) $root
                foreach sink $sinks {puts $edges "$driver\t$sink";incr edge_count}
                # External loads remain visible.  The driver is non-editable,
                # and this synthetic sink can never be mistaken for a cell pin.
                foreach port $ports {puts $edges "$driver\tbarrier PORT:$port";incr edge_count}
            }
        }
      }
    }
    runtime_row $runtime routes_and_edges $phase_tick $count
    set phase_tick [clock microseconds]
    # Nets do not expose disconnected pins.  Capture these explicitly so a
    # planner cannot mistake a missing LUT/MUX/FF input for a smaller cone.
    # Unused memory cascade/status pins remain barriers but do not invalidate
    # otherwise editable DIN/ADDR/BWE boundaries on the memory primitive.
    set supported_cells {};foreach name [array names rows] {
        if {[supported $all_refs($name)]} {lappend supported_cells $name}
    }
    set disconnected_count 0
    foreach batch [sb::chunks $supported_cells 1024] {
        set objects [get_cells -quiet $batch]
        sb::require [expr {[llength $objects]==[llength $batch]}] "Missing locality input-inventory cell"
        foreach pin [sb::names [get_pins -quiet -of_objects $objects -filter {IS_LEAF == 1 && DIRECTION == IN && IS_CLOCK == 0}]] {
            field $pin
            set cell [file dirname $pin];set ref $all_refs($cell)
            if {[clock_pin $pin $ref] || [info exists connected_inputs($pin)]} {continue}
            puts $edges "barrier UNCONNECTED:$pin\t$pin";incr edge_count;incr disconnected_count
            if {[regexp {^(LUT[1-6]|MUXF[789]|FDRE|FDSE)$} $ref]} {block $cell unconnected_input}
            puts $diag "unconnected_input\t$pin\t$ref";incr diagnostic_count
        }
    }
    runtime_row $runtime disconnected_inputs $phase_tick [llength $supported_cells]
    set phase_tick [clock microseconds]
    unset connected_inputs
    close $edges;close $diag
    set cf [open $out/cells.tsv.tmp w]
    puts $cf "name\tref\tslr\tx\ty\tinit\teditable\tstatus"
    set editable_count 0
    foreach name [lsort [array names rows]] {
        lassign $rows($name) ref loc init
        set position {{} {} {}}
        if {[info exists sites($loc)]} {set position $sites($loc)} \
        elseif {[supported $ref]} {block $name unknown_site_region}
        set editable [expr {[supported $ref] && ![llength $reasons($name)]}]
        incr editable_count $editable
        puts $cf [join [concat [list $name $ref] $position [list $init $editable [join $reasons($name) ,]]] \t]
    }
    close $cf
    set metadata [dict create schema locality-inventory-v1 status PASS \
        cells [array size rows] editable_cells $editable_count nets $count \
        edges $edge_count constant_edges $constant_edges clock_nets $clock_count \
        fixed_nets $fixed_count disconnected_inputs $disconnected_count diagnostics $diagnostic_count \
        elapsed_ms [expr {[clock milliseconds]-$started}] \
        cells_path $out/cells.tsv edges_path $out/edges.tsv diagnostics_path $out/diagnostics.tsv \
        semantics direct_leaf_pins_complete_nonclock_no_timing_queries]
    set mf [open $out/metadata.tsv.tmp w];puts $mf "key\tvalue"
    dict for {key value} $metadata {puts $mf "$key\t[field $value]"};close $mf
    runtime_row $runtime serialization $phase_tick [array size rows]
    close $runtime
    foreach name {cells edges diagnostics metadata runtime} {file rename -force $out/$name.tsv.tmp $out/$name.tsv}
    puts "LOCALITY_INVENTORY [clock seconds] complete cells=[dict get $metadata cells] edges=$edge_count elapsed_ms=[dict get $metadata elapsed_ms]"
    flush stdout
    return $metadata
}
