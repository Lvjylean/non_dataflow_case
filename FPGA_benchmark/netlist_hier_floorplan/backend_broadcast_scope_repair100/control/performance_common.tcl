# Isolated execution optimization; all graph and physical policies stay upstream.
namespace eval perf {
    variable disconnect_batch 2048
    variable connect_batch 2048
    variable create_batch 512
    variable pending {}
    variable queue_connections 0
    variable queue_regions 0
    variable region_order {}
    variable region_members; array set region_members {}
    variable region_spec; array set region_spec {}
    variable calls; array set calls {}
    variable elapsed; array set elapsed {}
}
proc perf::timed {kind script} {
    variable calls; variable elapsed
    set start [clock microseconds]
    set code [catch {uplevel 1 $script} result options]
    incr calls($kind)
    incr elapsed($kind) [expr {[clock microseconds]-$start}]
    if {$code} {return -options $options $result}
    return $result
}
proc perf::plain {names} {return [split [join $names \n] \n]}
proc perf::names {objects} {
    if {![llength $objects]} {return {}}
    set values [get_property NAME $objects]
    if {[llength $objects] == 1} {set values [list $values]}
    return [plain $values]
}
proc perf::disconnect_segment {name members} {
    variable disconnect_batch
    set net [timed resolve_disconnect_net [list get_nets [list $name]]]
    if {[llength $net] != 1} {error "Missing disconnect net: $name"}
    for {set i 0} {$i < [llength $members]} {incr i $disconnect_batch} {
        set batch [lrange $members $i [expr {$i+$disconnect_batch-1}]]
        set pins [timed resolve_disconnect_pins [list get_pins [plain $batch]]]
        if {[llength $pins] != [llength $batch]} {error "Missing disconnect pins on $name"}
        timed disconnect_native [list disconnect_net -net $net -pinlist $pins]
        unset pins
    }
}
proc perf::connect_many {named_pairs} {
    variable connect_batch
    set width [expr {2*$connect_batch}]
    for {set i 0} {$i < [llength $named_pairs]} {incr i $width} {
        set batch [lrange $named_pairs $i [expr {$i+$width-1}]]
        set net_names {}; set pin_names {}; array set seen {}
        foreach {n p} $batch {
            if {![info exists seen($n)]} {lappend net_names $n; set seen($n) 1}
            lappend pin_names $p
        }
        array unset seen *
        set nets [timed resolve_connect_nets [list get_nets [plain $net_names]]]
        set pins [timed resolve_connect_pins [list get_pins [plain $pin_names]]]
        if {[llength $nets] != [llength $net_names] || [llength $pins] != [llength $pin_names]} {
            error "Missing or duplicate connection objects"
        }
        array set net_objects {}; array set pin_objects {}
        foreach n [names $nets] obj $nets {set net_objects($n) $obj}
        foreach p [names $pins] obj $pins {set pin_objects($p) $obj}
        set pairs {}
        foreach {n p} $batch {lappend pairs $net_objects($n) $pin_objects($p)}
        timed connect_native [list connect_net -hierarchical -dict $pairs]
        unset pairs nets pins
        array unset net_objects *; array unset pin_objects *
    }
}
proc perf::flush_connections {} {
    variable pending
    if {[llength $pending]} {connect_many $pending; set pending {}}
}
proc perf::flush_regions {} {
    variable region_order; variable region_members; variable region_spec
    foreach name $region_order {
        set regions $region_spec($name)
        set pb [get_pblocks -quiet [list $name]]
        if {![llength $pb]} {
            set pb [create_pblock $name]
            set ranges {}; foreach cr $regions {lappend ranges CLOCKREGION_${cr}:CLOCKREGION_${cr}}
            resize_pblock $pb -add $ranges
            set_property EXCLUDE_PLACEMENT false $pb
            set_property IS_SOFT false $pb
        }
        foreach batch [sb::chunks $region_members($name) 512] {
            timed bind_native [list add_cells_to_pblock $pb [get_cells [plain $batch]]]
        }
    }
    set region_order {}; array unset region_members *; array unset region_spec *
}
proc perf::save {directory} {
    variable calls; variable elapsed
    file mkdir $directory
    set f [open $directory/execution_calls.tsv w]
    puts $f "operation\tcalls\telapsed_us"
    foreach name [lsort [array names calls]] {puts $f "$name\t$calls($name)\t$elapsed($name)"}
    close $f
}
