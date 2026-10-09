# Bounded native operations; no selection, logical grouping or placement policy.
if {[namespace exists ::execopt]} {return}
namespace eval execopt {
    variable enabled 0
    variable batch 2048
    variable pending {}
    variable region_order {}
    variable region_members; array set region_members {}
    variable region_spec; array set region_spec {}
    variable calls; array set calls {}
    variable elapsed; array set elapsed {}
}
proc execopt::configure {profile} {
    variable enabled
    if {$profile ni {fast reference}} {error "Unknown execution profile: $profile"}
    set enabled [expr {$profile eq "fast"}]
    clear_queues
}
proc execopt::clear_queues {} {
    variable pending; set pending {}
    variable region_order; set region_order {}
    variable region_members; array unset region_members *
    variable region_spec; array unset region_spec *
}
proc execopt::timed {kind script} {
    variable calls; variable elapsed
    set start [clock microseconds]
    set code [catch {uplevel 1 $script} result options]
    incr calls($kind)
    incr elapsed($kind) [expr {[clock microseconds]-$start}]
    if {$code} {return -options $options $result}
    return $result
}
proc execopt::plain {names} {return [split [join $names \n] \n]}
proc execopt::names {objects} {
    if {![llength $objects]} {return {}}
    set result [get_property NAME $objects]
    if {[llength $objects] == 1} {set result [list $result]}
    return [plain $result]
}
proc execopt::exact_objects {kind requested} {
    if {![llength $requested]} {return {}}
    set command [dict get {net get_nets pin get_pins cell get_cells} $kind]
    set objects [timed resolve_$kind [list $command [plain $requested]]]
    if {[llength $objects] != [llength $requested] ||
        [lsort [names $objects]] ne [lsort $requested]} {
        error "Missing, duplicate or unexpected $kind objects"
    }
    return $objects
}
proc execopt::disconnect_segment {net_name pins} {
    variable batch
    # Distinct hierarchical segments remain distinct native disconnect calls.
    set net [exact_objects net [list $net_name]]
    for {set i 0} {$i < [llength $pins]} {incr i $batch} {
        set objects [exact_objects pin [lrange $pins $i [expr {$i+$batch-1}]]]
        timed disconnect_native [list disconnect_net -net $net -pinlist $objects]
        unset objects
    }
}
proc execopt::connect_many {named_pairs} {
    variable batch
    if {[llength $named_pairs] % 2} {error "Incomplete net/pin pair"}
    array set seen_pins {}
    foreach {net pin} $named_pairs {
        if {[info exists seen_pins($pin)]} {error "Duplicate connection pin: $pin"}
        set seen_pins($pin) 1
    }
    set width [expr {2*$batch}]
    for {set i 0} {$i < [llength $named_pairs]} {incr i $width} {
        set pairs [lrange $named_pairs $i [expr {$i+$width-1}]]
        set net_names {}; set pin_names {}; array set seen_nets {}
        foreach {net pin} $pairs {
            if {![info exists seen_nets($net)]} {lappend net_names $net; set seen_nets($net) 1}
            lappend pin_names $pin
        }
        set nets [exact_objects net $net_names]
        set pins [exact_objects pin $pin_names]
        # Native collection order is not a correspondence guarantee.
        array set net_objects {}; array set pin_objects {}
        foreach name [names $nets] object $nets {set net_objects($name) $object}
        foreach name [names $pins] object $pins {set pin_objects($name) $object}
        set native_pairs {}
        foreach {net pin} $pairs {lappend native_pairs $net_objects($net) $pin_objects($pin)}
        timed connect_native [list connect_net -hierarchical -dict $native_pairs]
        unset nets pins native_pairs
        array unset seen_nets *; array unset net_objects *; array unset pin_objects *
    }
}
proc execopt::queue_connections {net pins} {
    variable pending; variable batch
    foreach pin $pins {lappend pending $net $pin}
    if {[llength $pending] >= 2*$batch} {flush_connections}
}
proc execopt::flush_connections {} {
    variable pending
    if {[llength $pending]} {connect_many $pending; set pending {}}
}
proc execopt::queue_region {node} {
    variable region_order; variable region_members; variable region_spec
    set regions [dict get $node regions]
    set name rfd_region_[join $regions _]
    if {![info exists region_members($name)]} {
        lappend region_order $name
        set region_spec($name) $regions
    } elseif {$region_spec($name) ne $regions} {error "Conflicting region queue: $name"}
    lappend region_members($name) [dict get $node name]
}
proc execopt::flush_regions {} {
    variable region_order; variable region_members; variable region_spec
    foreach name $region_order {
        set pb [get_pblocks -quiet [list $name]]
        if {![llength $pb]} {
            set pb [create_pblock $name]
            set ranges {}
            foreach cr $region_spec($name) {lappend ranges CLOCKREGION_${cr}:CLOCKREGION_${cr}}
            resize_pblock $pb -add $ranges
            set_property EXCLUDE_PLACEMENT false $pb
            set_property IS_SOFT false $pb
        }
        foreach batch [sb::chunks $region_members($name) 512] {
            set cells [exact_objects cell $batch]
            timed bind_native [list add_cells_to_pblock $pb $cells]
            unset cells
        }
    }
    set region_order {}; array unset region_members *; array unset region_spec *
}
proc execopt::save {directory mode} {
    variable enabled; variable calls; variable elapsed
    file mkdir $directory
    set f [open $directory/execution_${mode}.tsv w]
    puts $f "operation\tcalls\telapsed_us\tfast_enabled"
    foreach name [lsort [array names calls]] {puts $f "$name\t$calls($name)\t$elapsed($name)\t$enabled"}
    close $f
}
