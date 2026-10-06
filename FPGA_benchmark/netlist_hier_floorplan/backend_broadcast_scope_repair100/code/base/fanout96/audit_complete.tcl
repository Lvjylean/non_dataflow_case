# Complete physical coverage using conservative unions of whole electrical nets.
# A union below the limit proves the limit for every member; larger unions are
# split until exact single-net counts are measured. No logical-fanout prefilter.
proc f96::physical_batch {names file clock_file certificate_file} {
    variable target
    variable physical_bounds; variable physical_exact
    variable physical_count; variable physical_over; variable physical_max
    variable physical_clocks; variable physical_groups; variable physical_calls
    variable physical_route_status
    incr physical_calls
    set nets [get_nets -quiet $names]
    if {[lsort [values NAME $nets]] ne [lsort $names]} {error "Physical batch name resolution mismatch"}
    set clocks [get_clocks -quiet -of_objects $nets]
    set n -1
    set query_kind SEGMENT_EXACT_UNION
    if {![llength $clocks]} {
        set all_routed 1
        foreach name $names {if {$physical_route_status($name) ne "ROUTED"} {set all_routed 0; break}}
        if {$all_routed} {
            # Every actual external load of a fully routed net is attached to
            # one of its routed nodes. Include unused potential input pins too:
            # this is a conservative bound, never an exact fanout claim.
            set node_inputs [get_site_pins -quiet -of_objects [get_nodes -quiet -of_objects $nets] -filter {DIRECTION == IN}]
            set n [llength [lsort -unique [values NAME $node_inputs]]]
            set query_kind ROUTED_NODE_UPPER_BOUND
        }
        if {!$all_routed || $n > $target} {
            set segments [get_nets -quiet -segments $nets]
            set site_names [lsort -unique [values NAME [get_site_pins -quiet -of_objects $segments -filter {DIRECTION == IN}]]]
            set n [llength $site_names]
            set query_kind SEGMENT_EXACT_UNION
        }
    }
    set size [llength $names]
    if {$size > 1 && ([llength $clocks] || $n > $target)} {
        set middle [expr {$size / 2}]
        physical_batch [lrange $names 0 [expr {$middle-1}]] $file $clock_file $certificate_file
        physical_batch [lrange $names $middle end] $file $clock_file $certificate_file
        return
    }
    if {[llength $clocks]} {
        incr physical_clocks
        puts $clock_file "[lindex $names 0]\t[join $clocks ,]\tNOT_ENUMERATED"
        return
    }
    incr physical_count $size
    incr physical_groups
    set physical_max [expr {max($physical_max,$n)}]
    set exact [expr {$size == 1 && $query_kind eq "SEGMENT_EXACT_UNION"}]
    puts $certificate_file "$physical_groups\t$size\t$n\t$exact\t[list $names]\t$query_kind"
    foreach name $names {
        set physical_bounds($name) $n
        set physical_exact($name) $exact
    }
    if {$n > $target} {
        if {$size != 1} {error "An over-target batch was not resolved"}
        set loads [get_pins -quiet -of_objects $segments -filter {DIRECTION == IN && IS_LEAF == 1}]
        set clk 0; foreach flag [values IS_CLOCK $loads] {if {$flag} {incr clk}}
        set status ORDINARY_OVER_TARGET
        if {$clk} {set status CLOCK_LOAD_EXCEPTION}
        if {!$clk} {incr physical_over}
        puts $file "[lindex $names 0]\t$n\t[llength $loads]\t$clk\t$status"; flush $file
    }
}
proc f96::physical_all {directory} {
    variable target
    variable physical_bounds; array set physical_bounds {}
    variable physical_exact; array set physical_exact {}
    variable physical_count 0; variable physical_over 0; variable physical_max 0
    variable physical_clocks 0; variable physical_groups 0; variable physical_calls 0
    variable physical_route_status; array set physical_route_status {}
    file mkdir $directory
    set start [clock milliseconds]
    set segments [get_nets -hier -filter {TYPE != POWER && TYPE != GROUND}]
    set segment_count [llength $segments]
    set constant_segments [llength [get_nets -hier -filter {TYPE == POWER || TYPE == GROUND}]]
    set roots [get_nets -hier -segments -top_net_of_hierarchical_group -filter {TYPE != POWER && TYPE != GROUND}]
    set names [lsort -unique [values NAME $roots]]
    array set weight {}
    foreach name [values NAME $roots] pins [values FLAT_PIN_COUNT $roots] status [values ROUTE_STATUS $roots] {
        set weight($name) [expr {max(1,$pins-1)}]
        set physical_route_status($name) $status
    }
    phase "physical canonical_nets=[llength $names] nonconstant_segments=$segment_count"
    set f [open $directory/physical_over_target.tsv w]
    puts $f "net\tphysical\tlogical\tclock_sinks\tstatus"
    set cf [open $directory/clock_exceptions.tsv w]
    puts $cf "net\tclock_objects\tphysical_count"
    set bf [open $directory/batch_certificates.tsv w]
    puts $bf "group\tnets\tphysical_union_upper_bound\texact_single_net\tmember_names_tcl_list\tquery_kind"
    # These properties schedule queries only. No net is excluded and every
    # accepted bound still comes from the complete native SITE_PIN union.
    set batch {}; set score 0; set internal {}; set last_progress $start
    foreach name $names {
        if {$physical_route_status($name) eq "INTRASITE"} {
            lappend internal $name
            if {[llength $internal] >= 4096} {
                physical_batch $internal $f $cf $bf; set internal {}
            }
        } else {
            if {[llength $batch] && ($score+$weight($name) > 64 || [llength $batch] >= 256)} {
                physical_batch $batch $f $cf $bf; set batch {}; set score 0
            }
            lappend batch $name; incr score $weight($name)
            if {$score >= 64} {physical_batch $batch $f $cf $bf; set batch {}; set score 0}
        }
        if {[clock milliseconds]-$last_progress > 60000} {
            phase "physical covered=$physical_count clocks=$physical_clocks/[llength $names] groups=$physical_groups queries=$physical_calls elapsed_ms=[expr {[clock milliseconds]-$start}]"
            flush $bf; flush $cf
            set last_progress [clock milliseconds]
        }
    }
    if {[llength $batch]} {physical_batch $batch $f $cf $bf}
    if {[llength $internal]} {physical_batch $internal $f $cf $bf}
    if {$physical_count + $physical_clocks != [llength $names]} {error "Incomplete physical coverage"}
    close $f; close $cf; close $bf
    set f [open $directory/physical_summary.tsv w]
    puts $f "all_nonconstant_segments\tconstant_segments\tcanonical_nets\tordinary_nets_covered\tclock_nets_excluded\tordinary_over_target_nets\tordinary_max_physical_upper_bound\tcertificate_groups\tnative_queries\telapsed_ms"
    puts $f "$segment_count\t$constant_segments\t[llength $names]\t$physical_count\t$physical_clocks\t$physical_over\t$physical_max\t$physical_groups\t$physical_calls\t[expr {[clock milliseconds]-$start}]"; close $f
    return $physical_over
}
proc f96::helper_audit {directory} {
    variable target
    variable physical_bounds; variable physical_exact
    file mkdir $directory
    spatial_cache
    set cells [get_cells -quiet f96_identity_*]
    set f [open $directory/helpers.tsv w]
    puts $f "cell\tlogical\tphysical_upper_bound\tphysical_exact\thelper_slr\thelper_cr\tload_slrs\tload_cr_count\tunlocated_loads\tpblock\tin_soft_region"
    set count 0; set split 0; set crossing 0; set unresolved 0; set maxlog 0; set maxphy 0; set failures 0
    foreach c [values NAME $cells] pb [values PBLOCK $cells] {
        set pin [get_pins $c/O]
        set loads [loads $pin]
        set load_slrs {}; set load_crs {}; set unlocated 0
        foreach p [values NAME $loads] {
            set sr [region_of $p 1]; set region [region_of $p 0]
            dict set load_slrs $sr 1; dict set load_crs $region 1
            if {$sr eq "UNKNOWN"} {incr unlocated}
        }
        set n [llength $loads]
        set root [lsort -unique [values NAME [get_nets -segments -top_net_of_hierarchical_group -of_objects $pin]]]
        if {[llength $root] != 1} {error "Ambiguous helper canonical net: $c"}
        set root [lindex $root 0]
        if {![info exists physical_bounds($root)]} {error "Helper missing complete physical certificate: $root"}
        set physical $physical_bounds($root)
        set sr [region_of $pin 1]; set region [lindex [split [region_of $pin 0] /] end]
        set inside NA
        if {[string match f96_X* $pb]} {set inside [expr {$region eq [string range $pb 4 end]}]}
        if {[string match f96_SLR* $pb]} {set inside [expr {$sr eq [string range $pb 4 end]}]}
        puts $f "$c\t$n\t$physical\t$physical_exact($root)\t$sr\t$region\t[join [lsort [dict keys $load_slrs]] ,]\t[dict size $load_crs]\t$unlocated\t$pb\t$inside"
        set maxlog [expr {max($maxlog,$n)}]; set maxphy [expr {max($maxphy,$physical)}]
        if {$n > $target || $physical > $target} {incr failures}
        if {[dict size $load_slrs] > 1} {incr split}
        foreach load_slr [dict keys $load_slrs] {if {$load_slr ne $sr && $load_slr ne "UNKNOWN"} {incr crossing; break}}
        if {$unlocated || $sr eq "UNKNOWN"} {incr unresolved}
        incr count
        if {$count % 2000 == 0} {phase "helper_audit=$count/[llength $cells]"; flush $f}
    }
    close $f
    set f [open $directory/helper_summary.tsv w]
    puts $f "helpers\tmax_logical\tmax_physical_upper_bound\tover_target\tload_split_across_slrs\thelper_to_load_cross_slr\tunresolved_location"
    puts $f "$count\t$maxlog\t$maxphy\t$failures\t$split\t$crossing\t$unresolved"; close $f
}
