# Read-only, immutable locality inventory.  No timing queries or ECO commands.
# Source core.tcl and regional.tcl first.  Native handles remain in this process;
# the host planners consume only the streamed TSV files returned by capture.
namespace eval locality_inventory {
    variable shared_active 0
    variable capture_epoch {}; variable capture_folder {}
    variable rows; variable reasons; variable sites
    variable parent_protection; array set parent_protection {}
    variable protection_queries 0; variable protection_native_us 0
    array set rows {}; array set reasons {}; array set sites {}
}
proc locality_inventory::activate {} {
    if {![info exists ::vs::active] || !$::vs::active} {error "Live inventory reuse requires an immutable native read context"}
    vs::assert_readable
    # A capture performed outside this context cannot establish an immutable
    # relationship with a later native database, even in the same process.
    set ::locality_inventory::shared_active [expr {$::locality_inventory::capture_epoch ne "" && $::locality_inventory::capture_epoch eq $::vs::epoch}]
    return $::locality_inventory::shared_active
}
proc locality_inventory::deactivate {} {
    set ::locality_inventory::shared_active 0
    foreach var {connection_cells connection_nets} {
        if {[array exists ::locality_inventory::$var]} {array unset ::locality_inventory::$var *}
    }
    set ::locality_inventory::connection_epoch {}
    set ::locality_inventory::connection_cell_order {}
    set ::locality_inventory::connection_net_order {}
    if {[array exists ::locality_inventory::connection_clockless]} {array unset ::locality_inventory::connection_clockless *}
}
proc locality_inventory::cell_metadata {name} {
    variable shared_active;variable rows;variable sites
    if {!$shared_active || [input_mode] eq "reference" || ![info exists rows($name)]} {return {}}
    if {![info exists ::vs::active] || !$::vs::active} {error "Live inventory scope has ended"}
    vs::assert_readable
    if {$::locality_inventory::capture_epoch ne $::vs::epoch} {return {}}
    lassign $rows($name) ref loc init
    if {![info exists sites($loc)]} {return {}}
    lassign $sites($loc) slr x y
    connection_count cell_metadata_hits
    return [dict create name $name ref $ref slr $slr x $x y $y]
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
proc locality_inventory::canonical_index {objects target} {
    # Keep the original scalar handles for this capture only. Sorting names is
    # deterministic, but must never require resolving those names back to nets.
    upvar 1 $target by_name
    array set by_name {}
    foreach batch [sb::chunks $objects 2048] {
        set names [sb::names $batch]
        sb::require [expr {[llength $names] == [llength $batch]}] "Incomplete canonical net names"
        foreach object $batch name $names {
            sb::require [expr {$name ne ""}] "Missing canonical net name"
            field $name
            if {[info exists by_name($name)]} {
                sb::require [expr {$by_name($name) eq $object}] "Ambiguous canonical net handle: $name"
            } else {set by_name($name) $object}
        }
    }
    return [lsort [array names by_name]]
}
proc locality_inventory::group_segments {all_nets top_objects {runtime {}}} {
    # PARENT identifies the driver-side hierarchical group, not necessarily its
    # top segment. Map the authoritative top-net collection back to those groups.
    # A group must have exactly one top; absent/ambiguous metadata falls back to
    # the original native per-net query in capture, never to a guessed relation.
    # Parent-map dict construction was superlinear in real Vivado. Keep local
    # arrays during construction; expose the same
    # immutable dictionary interface only once, after every guard has passed.
    array set groups {};array set extra {};set tick [clock microseconds];set batch_index 0
    foreach objects [sb::chunks $top_objects 2048] {
        incr batch_index
        if {$runtime ne "" && $batch_index % 128 == 1} {
            puts "LOCALITY_PARENT_PROGRESS [clock seconds] top_batch=$batch_index";flush stdout
        }
        set names [sb::names $objects];set parents [sb::values PARENT $objects]
        sb::require [expr {[llength $names] == [llength $objects] && [llength $parents] == [llength $objects]}] "Incomplete canonical parent vectors"
        foreach name $names parent $parents {
            if {$parent eq ""} {error missing_net_parent}
            if {[info exists groups($parent)] && $groups($parent) ne $name} {error ambiguous_parent_group}
            set groups($parent) $name
        }
    }
    if {$runtime ne ""} {runtime_row $runtime canonical_parent_groups $tick [array size groups] 1}
    set tick [clock microseconds];set batch_index 0
    foreach batch [sb::chunks $all_nets 2048] {
        incr batch_index
        if {$runtime ne "" && $batch_index % 128 == 1} {
            puts "LOCALITY_PARENT_PROGRESS [clock seconds] segment_batch=$batch_index";flush stdout
        }
        set names [sb::names $batch];set parents [sb::values PARENT $batch]
        sb::require [expr {[llength $names] == [llength $batch] && [llength $parents] == [llength $batch]}] "Incomplete segment parent vectors"
        foreach object $batch name $names parent $parents {
            if {![info exists groups($parent)]} {error missing_parent_top_net}
            set root $groups($parent)
            if {$name ne $root} {lappend extra($root) $object}
        }
    }
    if {$runtime ne ""} {runtime_row $runtime canonical_segment_groups $tick [llength $all_nets] 1}
    return [array get extra]
}
proc locality_inventory::capture {out {profile {}}} {
    variable rows; variable reasons; variable sites
    foreach name {rows reasons sites} {array unset $name *}
    # Ancestor protection is stage-specific.  Do not carry a previous edit's
    # cached answer into this immutable snapshot.
    reset_protection
    deactivate
    set ::locality_inventory::capture_epoch {}
    set ::locality_inventory::capture_folder [file normalize $out]
    if {[info exists ::vs::active] && $::vs::active} {
        vs::assert_readable
        set ::locality_inventory::capture_epoch $::vs::epoch
    }
    if {$profile eq ""} {
        set profile batch
        if {[info exists ::env(BL_INVENTORY_PROFILE)]} {set profile $::env(BL_INVENTORY_PROFILE)}
    }
    if {$profile ni {reference batch}} {error "Unknown locality inventory profile: $profile"}
    set requested_profile $profile;set fallback_reason ""
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
    # These small records certify an edge-derived signal without retaining a
    # second full edge graph in Tcl. They include zero-load outputs, which do
    # not appear in edges.tsv. The targeted host snapshot checks sink counts.
    set reuse_nets [open $out/reuse_nets.tsv.tmp w]
    puts $reuse_nets "key\troot\ttype\tsinks\tsafe"
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
    set tick [clock microseconds]
    set top_objects [get_nets -quiet -segments -top_net_of_hierarchical_group $all_nets]
    runtime_row $runtime canonical_native_query $tick [llength $top_objects] 1
    set tick [clock microseconds]
    set roots [canonical_index $top_objects canonical_objects]
    runtime_row $runtime canonical_names_and_index $tick [llength $roots] 1
    # Native Vivado dict lookups on the full flat group table can take seconds
    # per root. Materialize the immutable table as a local array exactly once.
    array set extra_segments {}
    if {$profile eq "batch"} {
        set tick [clock microseconds]
        if {[catch {array set extra_segments [group_segments $all_nets $top_objects $runtime]} group_error]} {
            set fallback_reason $group_error;array unset extra_segments *;set profile reference
            puts "LOCALITY_INVENTORY native parent metadata unavailable; using complete reference queries: $fallback_reason"
        }
        runtime_row $runtime canonical_group_array $tick [array size extra_segments] 1
    }
    unset all_nets top_objects
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
    set connection_batch 0
    puts "LOCALITY_CONNECTIONS_BEGIN [clock seconds] roots=[llength $roots]";flush stdout
    foreach root_batch [sb::name_chunks $roots 2048] {
      incr connection_batch
      set batch_tick [clock microseconds]
      if {$connection_batch % 32 == 1} {
          puts "LOCALITY_CONNECTION_BATCH [clock seconds] batch=$connection_batch begin completed_nets=$count";flush stdout
      }
      set root_objects {}
      foreach root $root_batch {
          sb::require [info exists canonical_objects($root)] "Missing retained canonical locality net: $root"
          lappend root_objects $canonical_objects($root)
      }
      sb::require [expr {[llength $root_objects]==[llength $root_batch]}] "Missing canonical locality net batch"
      array set batch_names {};array set batch_directions {}
      if {$profile eq "batch"} {
          set batch_segments $root_objects
          foreach root $root_batch {
              if {[info exists extra_segments($root)]} {lappend batch_segments {*}$extra_segments($root)}
          }
          if {$connection_batch == 1} {runtime_row $runtime first_connection_group_expansion $batch_tick [llength $batch_segments] 1}
          set pin_tick [clock microseconds]
          set batch_pins [get_pins -quiet -of_objects $batch_segments -filter {IS_LEAF == 1 && (DIRECTION == OUT || IS_CLOCK == 0)}]
          if {$connection_batch == 1} {runtime_row $runtime first_connection_pin_query $pin_tick [llength $batch_pins] 1}
          set metadata_tick [clock microseconds]
          foreach object $batch_pins name [sb::names $batch_pins] direction [sb::values DIRECTION $batch_pins] {
              set batch_names($object) $name;set batch_directions($object) $direction
          }
          if {$connection_batch == 1} {runtime_row $runtime first_connection_pin_metadata $metadata_tick [array size batch_names] 1}
          unset batch_pins batch_segments
      }
      foreach net $root_objects root $root_batch type [sb::values TYPE $root_objects] {
        incr count
        if {$count % 4096 == 1} {
            puts "LOCALITY_INVENTORY [clock seconds] nets=$count/[llength $roots] edges=$edge_count"
            flush stdout;flush $edges;flush $diag
        }
        if {$profile eq "batch"} {
            set segments [list $net]
            if {[info exists extra_segments($root)]} {lappend segments {*}$extra_segments($root)}
        } else {set segments [get_nets -quiet -segments $net]}
        set pins [get_pins -quiet -of_objects $segments -filter {IS_LEAF == 1 && (DIRECTION == OUT || IS_CLOCK == 0)}]
        set drivers {};set sinks {};set other_pins {};set semantic_clocks {}
        set pin_names {};set pin_directions {}
        if {$profile eq "batch"} {
            foreach object $pins {
                sb::require [expr {[info exists batch_names($object)] && [info exists batch_directions($object)]}] "Missing batched leaf-pin metadata"
                lappend pin_names $batch_names($object);lappend pin_directions $batch_directions($object)
            }
        } else {set pin_names [sb::names $pins];set pin_directions [sb::values DIRECTION $pins]}
        foreach pin $pin_names direction $pin_directions {
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
        set isclock [expr {[info exists clocks($root)] || [llength $semantic_clocks]}]
        set reuse_fixed 0
        foreach segment $segments {if {[info exists fixed_segments($segment)]} {set reuse_fixed 1;break}}
        set reuse_safe [expr {$type ni {POWER GROUND} && !$isclock && !$reuse_fixed && [llength $drivers]==1 && ![llength $ports] && ![llength $other_pins]}]
        foreach driver $drivers {
            if {[supported $all_refs([file dirname $driver])]} {
                puts $reuse_nets "[field $driver]\t[field $root]\t[field $type]\t[llength $sinks]\t$reuse_safe"
            }
        }
        if {$type in {POWER GROUND}} {
            foreach sink $sinks {puts $edges "constant $type\t$sink";incr edge_count;incr constant_edges}
            continue
        }
        if {$isclock} {
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
      array unset batch_names *;array unset batch_directions *
    }
    unset extra_segments canonical_objects
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
    foreach batch [sb::name_chunks $supported_cells 1024] {
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
    close $edges;close $diag;close $reuse_nets
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
        acquisition_profile $profile requested_profile $requested_profile fallback_reason $fallback_reason \
        cells_path $out/cells.tsv edges_path $out/edges.tsv diagnostics_path $out/diagnostics.tsv \
        semantics direct_leaf_pins_complete_nonclock_no_timing_queries]
    dict set metadata reuse_schema targeted-native-input-v1
    dict set metadata reuse_epoch $::locality_inventory::capture_epoch
    set mf [open $out/metadata.tsv.tmp w];puts $mf "key\tvalue"
    dict for {key value} $metadata {puts $mf "$key\t[field $value]"};close $mf
    runtime_row $runtime serialization $phase_tick [array size rows]
    close $runtime
    foreach name {cells edges diagnostics metadata runtime reuse_nets} {file rename -force $out/$name.tsv.tmp $out/$name.tsv}
    puts "LOCALITY_INVENTORY [clock seconds] complete cells=[dict get $metadata cells] edges=$edge_count elapsed_ms=[dict get $metadata elapsed_ms]"
    flush stdout
    return $metadata
}
source [file join [file dirname [info script]] locality_input_snapshot.tcl]
