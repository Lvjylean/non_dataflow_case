# Live electrical-net inventory. Clock pins do not exempt unrelated data loads.
proc hf2::plain_values {property objects} {
    set values [f96::values $property $objects]
    if {![llength $values]} {return {}}
    # Native property scalar views can trigger repeated large collection copies.
    # Materialize names, booleans and reference-pin roles before Tcl traversal.
    set plain [lrange [split "__scalar__\n[join $values \n]" \n] 1 end]
    if {[llength $plain] != [llength $values]} {error "Newline in scalar property $property"}
    return $plain
}
proc hf2::sink_kind {pin} {
    return [sink_kind_values $pin [flag $pin IS_CLOCK] [get_property REF_PIN_NAME $pin]]
}
proc hf2::sink_kind_values {pin clock role} {
    if {$clock} {return CLOCK_PIN}
    if {$role ni {CI CI_TOP CYINIT} && ![regexp {^(ACIN|BCIN|PCIN|CARRYCASCIN|MULTSIGNIN|CAS_)} $role]} {return ORDINARY}
    # Materialized names are not native pin handles for -of_objects.
    set object [get_pins -quiet [list $pin]]
    if {[llength $object] != 1 || [get_property NAME $object] ne $pin} {
        error "Missing or ambiguous cascade candidate pin: $pin"
    }
    set cell [get_cells -quiet -of_objects $object]
    if {[llength $cell] != 1} {error "Expected one cell for cascade candidate pin: $pin"}
    set ref [get_property REF_NAME $cell]
    if {[regexp {^CARRY[48]$} $ref] && $role in {CI CI_TOP CYINIT}} {return CASCADE_PIN}
    if {[regexp {^(DSP|URAM)} $ref] && [regexp {^(ACIN|BCIN|PCIN|CARRYCASCIN|MULTSIGNIN|CAS_)} $role]} {
        return CASCADE_PIN
    }
    return ORDINARY
}
proc hf2::net_status {clock_object ref driver_count clock_count ordinary_count} {
    if {$ref in {VCC GND}} {return CONSTANT}
    if {$clock_object} {return CLOCK_DISTRIBUTION}
    if {$driver_count != 1} {return UNSUPPORTED_DRIVER_COUNT}
    if {$clock_count && !$ordinary_count} {return CLOCK_PIN_ONLY}
    if {$clock_count} {return MIXED_CLOCK_DATA}
    return SELECTED
}
proc hf2::discover {out {physical 0} {roots ALL} {include_small 0}} {
    file mkdir $out
    f96::phase "scan $out"
    set ::hf2::protection_cache [dict create]
    set ::hf2::protection_self [dict create]
    set ::hf2::protection_snapshot_ready 0
    if {$roots eq "ALL"} {
        set candidates [get_nets -hier -filter {FLAT_PIN_COUNT > 96 && TYPE != POWER && TYPE != GROUND}]
        set roots [get_nets -quiet -segments -top_net_of_hierarchical_group -of_objects [get_pins -quiet -of_objects $candidates]]
    }
    set f [open $out/high_fanout.tsv w]
    puts $f "net\tdriver\tref\tlogical\tphysical\tclock_loads\tstatus"
    set selected {}; set rows {}; set seen [dict create]; set excluded 0; set unsupported 0
    set scan_index 0
    foreach net $roots {
        incr scan_index
        if {$scan_index % 100 == 0} {f96::phase "scan_progress $out roots=$scan_index"}
        set name [get_property NAME $net]
        if {[dict exists $seen $name]} {continue}; dict set seen $name 1
        set clocks_here [get_clocks -quiet -of_objects $net]
        if {[llength $clocks_here]} {
            set row [dict create net $name driver {} ref CLOCK_OBJECT logical NOT_ENUMERATED physical NOT_ENUMERATED clock_loads [join $clocks_here ,] status CLOCK_DISTRIBUTION]
        } else {
            set segments [get_nets -quiet -segments $net]
            set sink_objects [get_pins -quiet -of_objects $segments -filter {DIRECTION == IN && IS_LEAF == 1}]
            set sink_names [f96::plain_names $sink_objects]
            set clock_values [plain_values IS_CLOCK $sink_objects]
            set role_values [plain_values REF_PIN_NAME $sink_objects]
            set kinds [dict create]
            if {[llength $sink_names] > 10000} {f96::phase "scan_large_begin $name loads=[llength $sink_names]"}
            foreach pin $sink_names clock $clock_values role $role_values {
                dict set kinds $pin [sink_kind_values $pin $clock $role]
            }
            if {[llength $sink_names] > 10000} {f96::phase "scan_large_classified $name"}
            set sinks [lsort -unique $sink_names]
            if {!$include_small && [llength $sinks] <= 96} {continue}
            set drivers [get_pins -quiet -of_objects $segments -filter {DIRECTION == OUT && IS_LEAF == 1}]
            set ports [get_ports -quiet -of_objects $segments -filter {DIRECTION == IN}]
            set driver_count [expr {[llength $drivers]+[llength $ports]}]
            # Port-driven and undriven nets have no leaf output pin collection.
            set ref {}
            if {[llength $drivers]} {
                set ref [join [f96::values REF_NAME [get_cells -quiet -of_objects $drivers]] ,]
            }
            set names [concat [f96::plain_names $drivers] [f96::plain_names $ports]]
            set ordinary_map [dict create]; set keep_map [dict create]; set clock_count 0
            # Iterating the sorted native-like pin list and looking up each key
            # is pathological on large Vivado nets. Traverse the existing map.
            dict for {pin kind} $kinds {
                if {$kind eq "ORDINARY"} {dict set ordinary_map $pin 1} else {dict set keep_map $pin 1}
                if {$kind eq "CLOCK_PIN"} {incr clock_count}
            }
            set ordinary [lsort [dict keys $ordinary_map]]
            set keep [lsort [dict keys $keep_map]]
            set status [net_status 0 $ref $driver_count $clock_count [expr {[llength $sinks]-$clock_count}]]
            set phy -1
            if {$physical} {set phy [llength [lsort -unique [f96::plain_names [get_site_pins -quiet -of_objects $segments -filter {DIRECTION == IN}]]]]}
            set row [dict create net $name driver [join $names ,] ref $ref logical [llength $sinks] physical $phy clock_loads $clock_count status $status]
            if {$status in {SELECTED MIXED_CLOCK_DATA}} {
                set driver [expr {[llength $drivers] ? [lindex $drivers 0] : [lindex $ports 0]}]
                lappend selected [dict create driver $driver driver_name [lindex $names 0] ref $ref net $name sinks $sinks ordinary_sinks $ordinary keep_sinks $keep sink_kinds $kinds]
            }
        }
        set status [dict get $row status]
        if {$status in {CONSTANT CLOCK_DISTRIBUTION CLOCK_PIN_ONLY}} {incr excluded}
        if {$status eq "UNSUPPORTED_DRIVER_COUNT"} {incr unsupported}
        lappend rows $row
        set fields {}; foreach key {net driver ref logical physical clock_loads status} {lappend fields [dict get $row $key]}
        puts $f [join $fields \t]
        flush $f
    }
    close $f
    set f [open $out/scan_summary.tsv w]
    puts $f "candidate_roots\thigh_fanout\tselected\texcluded\tunsupported_ordinary\tordinary_over_target\ttarget"
    puts $f "[dict size $seen]\t[llength $rows]\t[llength $selected]\t$excluded\t$unsupported\t[expr {[llength $selected]+$unsupported}]\t96"; close $f
    set result [acceptance_from_rows $rows]
    set f [open $out/acceptance.tsv w]; puts $f "metric\tvalue\nlogical_limit_exclusive\t100"
    dict for {key value} $result {puts $f "$key\t$value"}
    puts $f "physical_scope\t[expr {$physical ? "OVER_THRESHOLD_CANDIDATES_ONLY" : "NOT_MEASURED"}]\nfull_all_net_physical_certificate\tNOT_RUN"; close $f
    return $selected
}
proc hf2::scan {out {physical 0}} {return [discover $out $physical]}
