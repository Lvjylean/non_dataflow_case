# Read-only placement/routing comparison; one batched primitive inventory per DCP.
if {[catch {
lassign $argv checkpoint out input stage
set root [file dirname [file normalize [info script]]]
file mkdir $out
set_param general.maxThreads 8
source $root/code/base/fanout96/core.tcl
source $root/code/base/balanced_implementation/adapter.tcl
source $root/clock.tcl
if {![info exists ::audit_reuse_design] || !$::audit_reuse_design} {open_checkpoint $checkpoint}
compilefast_clock $out 0
bi_load $input
set f [open $out/module_constraints.tsv w]
puts $f "module\tsoft\tplanned_regions\tactual_ranges"
dict for {mid crs} $::planned_regions {
    set pb [get_pblocks -quiet hfp_$mid]
    if {[llength $pb] != 1 || ![get_property IS_SOFT $pb]} {error "Original module soft constraint changed: $mid"}
    # Range representation may be normalized, so compare the actual site sets.
    # Pblock resources omit some infrastructure sites; compare supported primitives only.
    set filter {NAME =~ SLICE_* || NAME =~ DSP48E2_* || NAME =~ RAMB18_* || NAME =~ RAMB36_* || NAME =~ URAM288_*}
    set wanted [lsort -unique [f96::values NAME [get_sites -of_objects [get_clock_regions $crs] -filter $filter]]]
    if {[llength [info commands bi_expected_sites]]} {set wanted [bi_expected_sites $mid]}
    set actual [lsort -unique [f96::values NAME [get_sites -of_objects $pb -filter $filter]]]
    if {$wanted ne $actual} {error "Original module range changed: $mid"}
    puts $f "$mid\t[get_property IS_SOFT $pb]\t$crs\t[get_property GRID_RANGES $pb]"
}
close $f
array set site_cr {}; array set cr_slr {}; array set allowed {}
foreach cr [get_clock_regions] {
    set name [get_property NAME $cr]
    set cr_slr($name) [get_property NAME [get_slrs -of_objects $cr]]
    foreach site [f96::values NAME [get_sites -of_objects $cr]] {set site_cr($site) $name}
}
dict for {mid crs} $::planned_regions {foreach cr $crs {set allowed($mid,$cr) 1}}
array set counts {}; array set spill {}; array set locations {}
set cells [get_cells -hier -filter {IS_PRIMITIVE == 1}]
set missing_location 0
foreach name [f96::values NAME $cells] ref [f96::values REF_NAME $cells] loc [f96::values LOC $cells] {
    if {![info exists site_cr($loc)]} {incr missing_location; continue}
    set cr $site_cr($loc)
    incr counts($cr,$ref)
    if {[info exists ::cf_owner($name)]} {
        set mid $::cf_owner($name)
        if {[dict exists $::planned_regions $mid]} {
            incr locations($mid,$cr)
            set where [expr {[info exists allowed($mid,$cr)] ? "inside" : "outside"}]
            if {[llength [info commands bi_cell_inside_soft]]} {
                set where [expr {[bi_cell_inside_soft $mid $ref $cr] ? "inside" : "outside"}]
            }
            incr spill($mid,$where)
        }
    }
}
unset cells
set f [open $out/cr_primitive_counts.tsv w]
puts $f "clock_region\tslr\tref\tplaced_primitive_count"
foreach key [lsort [array names counts]] {
    lassign [split $key ,] cr ref
    puts $f "$cr\t$cr_slr($cr)\t$ref\t$counts($key)"
}
close $f
set f [open $out/module_locations.tsv w]; puts $f "original_module\tclock_region\tretained_original_cells"
foreach key [lsort [array names locations]] {puts $f "[join [split $key ,] \t]\t$locations($key)"}
close $f
set f [open $out/soft_region_spill.tsv w]; puts $f "original_module\tinside_or_outside\tretained_original_cells"
foreach key [lsort [array names spill]] {puts $f "[join [split $key ,] \t]\t$spill($key)"}
close $f
set annotations [open $out/annotations.txt w]
puts $annotations "CR counts are placed primitive instances, not native utilization percentages or resource-normalized packing."
puts $annotations "Module counts use retained original cell names; new/renamed cells are not attributed by guesses."
puts $annotations "Primitives without mapped locations: $missing_location"
set shared [file normalize [file join $out .. reopened utilization_slr.rpt]]
if {$stage eq "routed" && [file isfile $shared] && [info exists ::audit_reuse_design] && $::audit_reuse_design} {
    file copy $shared $out/utilization_slr.rpt
} else {report_utilization -slr -file $out/utilization_slr.rpt}
report_utilization -hierarchical -hierarchical_depth 2 -file $out/utilization_hierarchy.rpt
if {[catch {report_design_analysis -congestion -file $out/congestion.rpt} error]} {puts $annotations "CONGESTION_UNAVAILABLE $error"}
if {$stage eq "routed"} {report_methodology -file $out/methodology.rpt}
# Global worst paths and selected data/CE families are emitted by sb::reports.
# No case-specific instance names are used in this physical audit.
close $annotations
set f [open $out/complete.txt w]; puts $f "Read-only $stage audit complete; original module soft ranges and requested clock verified."; close $f
if {![info exists ::audit_reuse_design] || !$::audit_reuse_design} {close_design; exit}
} message options]} {
    puts stderr [dict get $options -errorinfo]
    exit 1
}
