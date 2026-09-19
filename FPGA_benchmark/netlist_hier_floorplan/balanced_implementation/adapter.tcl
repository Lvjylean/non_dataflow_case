# Frozen membership adapter; keep original netlist hierarchy intact.
proc bi_load {input} {
    source $input/regions.tcl
    set ::planned_regions $planned_regions
    set ::planned_bounds $planned_bounds
    set ::cf_large __NO_SEPARATE_DSP_CHILD__
    foreach a {cf_owner cf_resource cf_ref cf_members} {array unset ::$a; array set ::$a {}}
    set f [open $input/membership.tsv r]; gets $f header
    while {[gets $f line] >= 0} {
        lassign [split $line \t] name mid resource ref
        if {[info exists ::cf_owner($name)]} {error "Duplicate member: $name"}
        set ::cf_owner($name) $mid; set ::cf_resource($name) $resource; set ::cf_ref($name) $ref
        if {[dict exists $::planned_regions $mid]} {lappend ::cf_members($mid) $name}
    }
    close $f
}

proc bi_apply {out} {
    if {[llength [get_pblocks -quiet hfp_*]] || [llength [get_cells -quiet f96_identity_*]]} {
        error "Expected the clean post-opt reference, not an earlier physical experiment"
    }
    set f [open $out/constraint_binding.tsv w]
    puts $f "module\texpected\tfound\tsoft\tclock_region_rectangle"
    dict for {mid bounds} $::planned_bounds {
        lassign $bounds x0 y0 x1 y1
        set names $::cf_members($mid)
        set cells [get_cells -quiet $names]
        if {[lsort [f96::values NAME $cells]] ne [lsort $names]} {error "Exact primitive name binding mismatch: $mid"}
        set pb [create_pblock hfp_$mid]
        set range CLOCKREGION_X${x0}Y${y0}:CLOCKREGION_X${x1}Y${y1}
        resize_pblock $pb -add $range
        set_property IS_SOFT true $pb
        add_cells_to_pblock $pb $cells
        puts $f "$mid\t[llength $names]\t[llength $cells]\t[get_property IS_SOFT $pb]\t$range"
    }
    close $f
    if {[bi_geometry $out/geometry_initial 1]} {error "Initial native binding/geometry failed"}
}

proc bi_geometry {out {require_all 0}} {
    file mkdir $out
    array set found {}; array set good {}; array set bad {}
    set f [open $out/binding_mismatches.tsv w]; puts $f "cell\texpected\tactual"
    set cells [get_cells -hier -filter {IS_PRIMITIVE == 1}]
    foreach name [f96::values NAME $cells] pb [f96::values PBLOCK $cells] {
        if {![info exists ::cf_owner($name)]} {continue}
        set mid $::cf_owner($name)
        if {![dict exists $::planned_regions $mid]} {continue}
        set found($name) 1
        if {$pb eq "hfp_$mid"} {incr good($mid)} else {incr bad($mid); puts $f "$name\thfp_$mid\t$pb"}
    }
    close $f
    set failures 0
    set f [open $out/binding.tsv w]
    puts $f "module\toriginal\tretained_matching\tretained_mismatch\tabsent_original_names\tsoft"
    set g [open $out/site_geometry.tsv w]
    puts $g "module\texpected_sites\tactual_sites\texact_match\tparent"
    set filter {NAME =~ SLICE_* || NAME =~ DSP48E2_* || NAME =~ RAMB18_* || NAME =~ RAMB36_* || NAME =~ URAM288_*}
    dict for {mid crs} $::planned_regions {
        foreach a {good bad} {if {![info exists ${a}($mid)]} {set ${a}($mid) 0}}
        set expected [llength $::cf_members($mid)]
        set absent [expr {$expected - $good($mid) - $bad($mid)}]
        set pb [get_pblocks hfp_$mid]; set soft [get_property IS_SOFT $pb]
        puts $f "$mid\t$expected\t$good($mid)\t$bad($mid)\t$absent\t$soft"
        set wanted [lsort -unique [f96::values NAME [get_sites -of_objects [get_clock_regions $crs] -filter $filter]]]
        set actual [lsort -unique [f96::values NAME [get_sites -of_objects $pb -filter $filter]]]
        set exact [expr {$wanted eq $actual}]
        puts $g "$mid\t[llength $wanted]\t[llength $actual]\t$exact\t[get_property PARENT $pb]"
        if {$bad($mid) || !$soft || !$exact || ($require_all && $absent)} {incr failures}
    }
    close $f; close $g
    return $failures
}

proc bi_protect {} {
    set helpers [get_cells -quiet f96_identity_*]
    if {[llength $helpers]} {
        set roots [get_nets -segments -of_objects [get_pins -of_objects $helpers -filter {DIRECTION == IN}]]
        if {[llength $roots]} {set_property DONT_TOUCH true $roots}
    }
}

proc bi_snapshot {out stage} {
    file mkdir $out/$stage
    write_checkpoint $out/$stage.dcp
    report_utilization -file $out/$stage/utilization.rpt
    report_timing_summary -delay_type min_max -file $out/$stage/timing_summary.rpt
}

proc bi_patch {items out} {
    set before [llength [get_cells -hier -filter {IS_PRIMITIVE == 1 && REF_NAME =~ FD*}]]
    f96::apply $items $out
    set after [llength [get_cells -hier -filter {IS_PRIMITIVE == 1 && REF_NAME =~ FD*}]]
    set f [open $out/register_check.tsv w]
    puts $f "before_ff\tafter_ff\tnew_pipeline_stages"; puts $f "$before\t$after\t0"; close $f
    if {$before != $after} {error "Manual identity transformation changed register count"}
    bi_protect
}
