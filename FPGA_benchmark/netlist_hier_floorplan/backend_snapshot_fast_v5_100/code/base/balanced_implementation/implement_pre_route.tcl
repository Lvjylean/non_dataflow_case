set_param general.maxThreads 8
lassign $argv input checkpoint out mode inherited
if {[file exists $out]} {error "Refusing to replace an implementation"}
file mkdir $out
set here [file dirname [file normalize [info script]]]
source $here/../fanout96/core.tcl
source $here/../fanout96/fast.tcl
source $here/../fanout96/quick.tcl
source $here/../fanout96/hybrid.tcl
source [file join $here ../../../control/performance_base.tcl]
source $here/adapter.tcl
bi_load $input
f96::phase open_postopt
if {![info exists ::compilefast::active] || !$::compilefast::active} {open_checkpoint $checkpoint}
if {$mode eq "seed"} {
    if {![file exists $inherited/seed_place.dcp]} {error "Missing immutable seed placement"}
    foreach name {constrained.dcp seed_place.dcp floorplan_constraints.xdc} {
        file link -hard $out/$name $inherited/$name
    }
    foreach name {constrained seed_place geometry_initial constraint_binding.tsv} {
        file copy $inherited/$name $out/$name
    }
    set f [open $out/source_stages.txt w]
    puts $f "Inherited constrained and seed placement stages from $inherited; input=$checkpoint"; close $f
    if {[bi_geometry $out/geometry_seed_reopened]} {error "Reopened seed binding/geometry mismatch"}
} else {
    bi_apply $out
}
# Remove stale inherited replication targets consistently for both candidates.
set forced [get_nets -hier -filter {FORCE_MAX_FANOUT > 0}]
set f [open $out/reset_replication_active.tsv w]; puts $f "net"
foreach n [f96::values NAME $forced] {puts $f $n}; close $f
if {[llength $forced]} {reset_property FORCE_MAX_FANOUT $forced}
if {$mode ne "seed"} {
    write_xdc $out/floorplan_constraints.xdc
    bi_snapshot $out constrained
    # A fresh seed placement provides geometry for the existing spatial tree flow.
    f96::phase seed_place
    plg::place $out/physical_seed
    bi_snapshot $out seed_place
}
f96::spatial_cache
# Match the existing fanout96 flow: cache placement, remove partial routes,
# and discover initial targets logically. Physical counting is diagnostic here
# and is extremely expensive on untouched very-high-fanout controls.
route_design -unroute
f96::phase fanout_begin
set selected [f96::scan $out/before 0]
lassign [f96::split_actions $selected $out/actions_0] editable native unsupported
bi_patch $editable $out/patch_0
# Seed and final DCPs are retained; omit the transient prepared checkpoint.
f96::phase fanout_place
plg::place $out/physical_fanout -no_psip -no_bufg_opt
file mkdir $out/post_place
report_utilization -file $out/post_place/utilization.rpt
report_timing_summary -delay_type min_max -file $out/post_place/timing_summary.rpt
f96::phase phys_opt
phys_opt_design
set current [f96::required [f96::scan $out/native_current_0 0]]
lassign [f96::split_actions $current $out/native_actions_0] pending native unsupported
f96::force_native $native $out/native_0
bi_protect
# Keep a timing/utilization record without saving a DCP on every refinement.
file mkdir $out/post_phys_opt
report_utilization -file $out/post_phys_opt/utilization.rpt
report_timing_summary -delay_type min_max -file $out/post_phys_opt/timing_summary.rpt
set prior_signature {}
set stop_reason max_passes
set stop_file [open $out/refinement_stop.tsv w]
puts $stop_file "pass\treason\tordinary_ge100"
for {set pass 1} {$pass <= 7} {incr pass} {
    set residual [f96::required [f96::scan $out/refinement_$pass 0]]
    if {![llength $residual]} {set stop_reason below_100; break}
    set signature [f96::residual_signature $residual]
    if {$prior_signature ne "" && $signature eq $prior_signature} {
        set stop_reason unchanged_exact_driver_sink_sets_after_native80
        f96::phase "native_no_progress pass=$pass residual=[llength $residual]"
        break
    }
    set prior_signature $signature
    lassign [f96::split_actions $residual $out/actions_$pass] editable native unsupported
    if {[llength $editable]} {
        f96::spatial_cache
        bi_patch $editable $out/patch_$pass
        f96::phase "strict_place=$pass editable=[llength $editable]"
        plg::place $out/physical_refinement_$pass -no_psip -no_bufg_opt
        set current [f96::required [f96::scan $out/native_current_$pass 0]]
        lassign [f96::split_actions $current $out/native_actions_$pass] pending native unsupported
    }
    foreach item $native {set_property FORCE_MAX_FANOUT 80 [get_nets -of_objects [dict get $item driver]]}
    f96::force_native $native $out/native_$pass
    bi_protect
    if {![llength $editable] && ![llength $native]} {set stop_reason no_editable_or_native; break}
}
puts $stop_file "$pass\t$stop_reason\t[llength $residual]"; close $stop_file
set residual [f96::required [f96::scan $out/pre_route_scan 0]]
f96::phase fanout_end
# The generic structural ECO consumes this placed, not routed, checkpoint.
f96::phase save_pre_route
bi_snapshot $out pre_route
write_xdc $out/applied_constraints.xdc
set f [open $out/complete.txt w]
puts $f "Fanout and placement preparation complete; no full route_design executed."
close $f
if {![info exists ::compilefast::active] || !$::compilefast::active} {close_design; exit}
