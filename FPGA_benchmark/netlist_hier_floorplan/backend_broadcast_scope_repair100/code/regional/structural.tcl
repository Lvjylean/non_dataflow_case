# Full-netlist structural candidate discovery. No timing path queries are used.
proc sb::structural_seeds {out min_fanout} {
    variable cell_objects
    variable refs
    variable site_slrs
    set start [clock seconds]
    # Resolve reference types and physical positions lazily for candidate cells.
    # Do not build an all-primitive object index or enumerate every device site.
    puts "SBECO_STRUCTURE $start candidate_metadata_on_demand"; flush stdout
    # Positions are fetched only for structurally eligible endpoints.
    puts "SBECO_STRUCTURE [clock seconds] candidate_nets"; flush stdout
    # Only FF Q outputs and FF CE inputs can seed the supported transformations.
    set ffs [get_cells -hier -filter {IS_PRIMITIVE == 1 && (REF_NAME == FDRE || REF_NAME == FDSE)}]
    set seed_pins [get_pins -quiet -of_objects $ffs -filter {REF_PIN_NAME == Q || REF_PIN_NAME == CE}]
    set roots [get_nets -quiet -segments -top_net_of_hierarchical_group -of_objects $seed_pins -filter "FLAT_PIN_COUNT > $min_fanout && TYPE != POWER && TYPE != GROUND"]
    array set seen {}; set candidates {}; set ce_targets {}; set visited 0
    set f [open $out/structural_signals.tsv w]
    puts $f "net\tdriver\tref\tlogical_loads\tce_loads\tstatus"
    puts "SBECO_STRUCTURE [clock seconds] root_collection=[llength $roots]"; flush stdout
    foreach n $roots {
        set net [get_property NAME $n]
        if {[info exists seen($net)]} {continue}
        set seen($net) 1
        incr visited
        if {$visited % 256 == 1} {puts "SBECO_STRUCTURE [clock seconds] nets=$visited"; flush stdout; flush $f}
        if {[llength [get_clocks -quiet -of_objects $n]]} {
            puts $f "$net\t\tCLOCK\tNOT_ENUMERATED\t0\tskip_clock"
            continue
        }
        set tick [clock milliseconds]
        puts "SBECO_NET_BEGIN $visited $net"; flush stdout
        set segments [get_nets -quiet -segments -of_objects [get_pins -quiet -of_objects $n]]
        set ds [names [get_pins -quiet -of_objects $segments -filter {DIRECTION == OUT && IS_LEAF == 1}]]
        if {[llength $ds] != 1} {puts $f "$net\t[join $ds ,]\t\t\t0\tskip_driver_count"; continue}
        set driver [lindex $ds 0]; set dc [file dirname $driver]; set dr [ref $dc]
        if {![regexp {^(FDRE|FDSE|LUT[1-6])$} $dr]} {
            puts $f "$net\t$driver\t$dr\tNOT_ENUMERATED\t0\tskip_driver_type"
            continue
        }
        if {$dr in {FDRE FDSE} && [file tail $driver] eq "Q"} {
            # Exact fanout is checked by scan; do not expand Q loads twice.
            dict set candidates $dc 1
            puts $f "$net\t$driver\t$dr\tDEFERRED\t0\tFF_structure_candidate"
        } elseif {[regexp {^LUT[1-6]$} $dr] && [file tail $driver] eq "O"} {
            # Query only CE pins before any position or full-load expansion.
            set sinks [lsort -unique [names [get_pins -quiet -of_objects $segments -filter {DIRECTION == IN && IS_LEAF == 1 && REF_PIN_NAME == CE}]]]
            if {![llength $sinks]} {
                puts $f "$net\t$driver\t$dr\tNOT_ENUMERATED\t0\tskip_no_CE"
                continue
            }
            set all_load_count [llength [get_pins -quiet -of_objects $segments -filter {DIRECTION == IN && IS_LEAF == 1}]]
            if {$all_load_count < $min_fanout} {continue}
            set count 0
            set source [dict get [position $dc] slr]
            foreach p $sinks {
                if {[file tail $p] ne "CE"} {continue}
                set c [file dirname $p]
                if {[ref $c] ni {FDRE FDSE}} {continue}
                set slr [dict get [position $c] slr]
                if {$slr eq $source} {continue}
                dict set ce_targets $c $slr
                incr count
            }
            puts $f "$net\t$driver\t$dr\t[llength $sinks]\t$count\tLUT_CE_structure_candidate"
        }
        puts "SBECO_NET_END $visited milliseconds=[expr {[clock milliseconds]-$tick}]"; flush stdout
    }
    close $f
    puts "SBECO_STRUCTURE [clock seconds] complete roots=$visited FF=[dict size $candidates] CE=[dict size $ce_targets] seconds=[expr {[clock seconds]-$start}]"
    return [dict create data_candidates [lsort [dict keys $candidates]] ce_targets $ce_targets net_roots $visited]
}
