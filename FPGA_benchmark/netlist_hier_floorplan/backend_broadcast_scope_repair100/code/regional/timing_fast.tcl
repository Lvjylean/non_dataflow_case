# Read every guarded endpoint; optimize extraction, never the acceptance rules.
namespace eval jif {
    variable batch_size 2048
}
proc jif::timed {path phase script} {
    set start [clock microseconds]
    set status [catch {uplevel 1 $script} result options]
    set fresh [expr {![file exists ${path}.runtime.tsv]}]
    set f [open ${path}.runtime.tsv a]
    if {$fresh} {puts $f "phase\telapsed_us\treturncode"}
    puts $f "$phase\t[expr {[clock microseconds]-$start}]\t$status";close $f
    if {$status} {return -options $options $result}
    return $result
}
proc jif::values {property objects} {
    if {![llength $objects]} {return {}}
    set values [get_property $property $objects]
    if {[llength $objects]==1} {set values [list $values]}
    if {[llength $values]!=[llength $objects]} {error "Timing property cardinality mismatch: $property"}
    return $values
}
proc jif::finite {value} {
    if {![string is double -strict $value]} {return 0}
    if {[catch {expr {abs(double($value))<1.0e30}} result]} {return 0}
    return $result
}
proc jif::write_slacks {pins observed path} {
    # Do not repeatedly convert/search the large native-backed dict while
    # writing each endpoint. Materialize small rows once, then use an array.
    array set rows {}
    dict for {pin data} $observed {
        set row {}
        foreach type {max min requirement} {
            lappend row [expr {[dict exists $data $type] ? [dict get $data $type] : ""}]
        }
        set rows($pin) [join $row \t]
    }
    set f [open ${path}.tmp w];puts $f "pin\tmax\tmin\trequirement"
    foreach pin $pins {
        if {[info exists rows($pin)]} {puts $f "$pin\t$rows($pin)"} else {puts $f "$pin\t\t\t"}
    }
    close $f;file rename -force ${path}.tmp $path
}
proc jif::path_slacks {pins path} {
    # Candidate planning still needs the path REQUIREMENT, so retain its search.
    # Read each returned collection's properties in bulk, mapped by endpoint.
    set pins [lsort -unique $pins];set observed {}
    foreach batch [sb::chunks $pins 512] {
        set objects [get_pins -quiet $batch]
        if {![llength $objects]} {continue}
        foreach type {max min} {
            set paths [timed $path search_$type [list get_timing_paths -to $objects -delay_type $type -max_paths [llength $batch] -nworst 1]]
            set endpoints [timed $path endpoints [list values ENDPOINT_PIN $paths]]
            set slacks [timed $path slack_values [list values SLACK $paths]]
            if {$type eq "max"} {set requirements [timed $path requirements [list values REQUIREMENT $paths]]}
            set i 0
            foreach endpoint $endpoints value $slacks {
                if {![finite $value]} {error "Non-finite path slack for $endpoint: $value"}
                if {![dict exists $observed $endpoint $type] || $value<[dict get $observed $endpoint $type]} {
                    dict set observed $endpoint $type $value
                    if {$type eq "max"} {dict set observed $endpoint requirement [lindex $requirements $i]}
                }
                incr i
            }
        }
    }
    timed $path write_rows [list write_slacks $pins $observed $path]
    return $observed
}
proc jif::guard_slacks {pins path} {
    variable batch_size
    if {[info exists ::env(JI_TIMING_MODE)] && $::env(JI_TIMING_MODE) eq "reference"} {
        return [timed $path reference [list ji::slacks_reference $pins $path]]
    }
    set pins [lsort -unique $pins];set observed {};set fallback {};set global_ports {}
    # No cross-stage cache: each call updates the current netlist/placement timer.
    timed $path update_timing {update_timing}
    foreach batch [sb::chunks $pins $batch_size] {
        set objects [timed $path resolve_pins [list get_pins -quiet $batch]]
        set names [timed $path names [list values NAME $objects]]
        if {[lsort $names] ne [lsort $batch]} {
            set missing {};foreach pin $batch {if {[lsearch -exact $names $pin]<0} {lappend missing $pin}}
            # all_fanout and top paths may include output PORT objects. The
            # archived guard queried get_pins only: these are protected by its
            # mandatory global summary, not per-pin floors. Preserve that scope
            # explicitly, while unknown/missing pins must still stop the flow.
            set ports [timed $path resolve_ports [list get_ports -quiet $missing]]
            set port_names [values NAME $ports]
            if {![llength $missing] || [lsort $port_names] ne [lsort $missing] ||
                [lsort [concat $names $port_names]] ne [lsort $batch]} {
                error "Missing/ambiguous guarded timing endpoint: requested=[llength $batch] resolved=[llength $names] missing=[lrange $missing 0 15]"
            }
            lappend global_ports {*}$port_names
        }
        foreach type {max min} property {SETUP_SLACK HOLD_SLACK} {
            set result [timed $path $property [list values $property $objects]]
            foreach name $names value $result {
                if {[finite $value]} {
                    dict set observed $name $type $value
                } else {
                    # Empty/infinite properties are never assumed to pass.
                    # Resolve these endpoints using the original path search.
                    lappend fallback $name
                }
            }
        }
    }
    set fallback [lsort -unique $fallback]
    if {[llength $fallback]} {
        set explicit [path_slacks $fallback ${path}.fallback.tsv]
        foreach pin $fallback {
            foreach type {max min} {
                if {[dict exists $explicit $pin $type]} {
                    dict set observed $pin $type [dict get $explicit $pin $type]
                } elseif {[dict exists $observed $pin $type]} {
                    error "Pin/path timing coverage conflict: $pin $type"
                }
            }
        }
    }
    timed $path write_rows [list write_slacks $pins $observed $path]
    set f [open ${path}.coverage.tsv w]
    puts $f "endpoints\tfallback_endpoints\ttimed_setup\ttimed_hold\tglobal_summary_ports"
    set setup 0;set hold 0
    dict for {pin data} $observed {incr setup [dict exists $data max];incr hold [dict exists $data min]}
    puts $f "[llength $pins]\t[llength $fallback]\t$setup\t$hold\t[llength $global_ports]";close $f
    set f [open ${path}.global_ports.txt w];foreach port $global_ports {puts $f $port};close $f
    return $observed
}
