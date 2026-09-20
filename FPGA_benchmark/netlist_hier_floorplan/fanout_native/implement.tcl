set_param general.maxThreads 8
lassign $argv input checkpoint out config
if {[file exists $out]} {error "Refusing to replace implementation evidence"}
file mkdir $out
set here [file dirname [file normalize [info script]]]
source $here/core.tcl
source $here/../balanced_implementation/adapter.tcl
source $config
hf2::configure $hf2_config
bi_load $input
open_checkpoint $checkpoint
if {[llength [get_cells -quiet hfg_identity_*]]} {error "Expected a clean post-opt checkpoint"}
bi_apply $out
set initial_ff [hf2::ff_count]
f96::phase fanout_begin
if {[catch {hf2::implement $out} detail options]} {
    set f [open $out/error_info.txt w]
    puts $f [dict get $options -errorinfo]; close $f
    puts stderr [dict get $options -errorinfo]
    return -options $options $detail
}
write_checkpoint $out/post_route.dcp
write_xdc $out/applied_constraints.xdc
report_timing_summary -delay_type min_max -file $out/post_route/timing_summary.rpt
report_route_status -file $out/post_route/route_status.rpt
report_utilization -slr -file $out/post_route/utilization_slr.rpt
report_drc -file $out/post_route/drc.rpt
report_methodology -file $out/post_route/methodology.rpt
report_timing -delay_type max -max_paths 1000 -nworst 1000 -unique_pins -file $out/post_route/worst1000.rpt
set f [open $out/register_counts.tsv w]
puts $f "postopt_ff\tfinal_ff\tmanual_pipeline_stages\tinterpretation"
puts $f "$initial_ff\t[hf2::ff_count]\t0\tNATIVE_REGISTER_REPLICATION_ALLOWED"; close $f
set f [open $out/complete.txt w]
puts $f "Implementation completed with one place_design call. Timing/fanout/spill are independent measured annotations; see post_route/fanout/acceptance.tsv."; close $f
close_design
exit
