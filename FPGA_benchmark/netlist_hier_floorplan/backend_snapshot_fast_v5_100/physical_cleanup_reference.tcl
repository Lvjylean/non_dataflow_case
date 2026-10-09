# Frozen 512-net cleanup used only by equivalence tests and the native probe.
# Production callers must use plg::clean_sites from physical_eco.tcl.
proc plg::clean_sites_legacy512 {site_names out {old_nets {}}} {
    file mkdir $out
    set normal {}; set clocks {}; set constants 0; set ordinary_calls 0
    foreach batch [batches [lsort -unique $site_names]] {
        set sites [exact site $batch]
        set cells [get_cells -quiet -of_objects $sites]
        if {![llength $cells]} {continue}
        set pins [get_pins -quiet -of_objects $cells]
        set cp [filter $pins {IS_CLOCK == 1}]
        if {[llength $cp]} {
            foreach n [names [get_nets -quiet -segments -of_objects $cp]] {dict set clocks $n 1}
        }
        set dp [filter $pins {IS_CLOCK == 0}]
        if {![llength $dp]} {continue}
        set nets [get_nets -quiet -segments -of_objects $dp]
        collect_routes $nets normal constants
    }
    foreach batch [batches $old_nets] {
        collect_routes [get_nets -quiet $batch] normal constants
    }
    foreach name [dict keys $clocks] {if {[dict exists $normal $name]} {dict unset normal $name}}
    set f [open $out/unroute.tsv w]; puts $f "net\taction"
    foreach batch [batches [dict keys $normal]] {
        route_design -unroute -nets [exact net $batch]
        incr ordinary_calls
        foreach n $batch {puts $f "$n\tordinary_incident_net"}
    }
    if {$constants} {route_design -unroute -physical_nets; puts $f "VCC_GND_PHYSICAL_NETS\tphysical_constant_cleanup"}
    foreach n [dict keys $clocks] {puts $f "$n\tclock_preserved"}
    close $f
    return [dict create completed 1 batch_size 512 ordinary_nets [dict size $normal] clock_aliases [dict size $clocks] ordinary_completed_calls $ordinary_calls physical_constant_completed_calls $constants]
}
