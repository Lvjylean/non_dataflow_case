set_param general.maxThreads 8
lassign $argv input checkpoint out config identity_manifest
if {[file exists $out]} {error "Refusing to replace readback evidence"}
file mkdir $out
set here [file dirname [file normalize [info script]]]
source $here/core.tcl
source $here/../balanced_implementation/adapter.tcl
source $here/../connection_floorplan/audit.tcl
source $config
hf2::configure $hf2_config
set ::hf2::identity_manifest $identity_manifest
bi_load $input
open_checkpoint $checkpoint
report_timing_summary -delay_type min_max -file $out/timing_summary.rpt
report_route_status -file $out/route_status.rpt
report_utilization -slr -file $out/utilization_slr.rpt
set geometry [bi_geometry $out/geometry]
cf_audit_regions $out/regions
hf2::scan $out/fanout 1
hf2::audit_identities $out
hf2::assert_placed_helpers
f96::spatial_cache
set f [open $out/worst_path_endpoints.tsv w]
puts $f "startpoint\tendpoint\tslack\tstart_slr\tend_slr\tstart_cr\tend_cr"
foreach path [get_timing_paths -delay_type max -max_paths 1000 -nworst 1000 -unique_pins] {
    set start [get_property STARTPOINT_PIN $path]; set end [get_property ENDPOINT_PIN $path]
    puts $f "$start\t$end\t[get_property SLACK $path]\t[f96::region_of $start 1]\t[f96::region_of $end 1]\t[f96::region_of $start 0]\t[f96::region_of $end 0]"
}
close $f
set f [open $out/complete.txt w]
puts $f "Independent readback completed; geometry_failures=$geometry. Native FF count may increase without new pipeline stages. Fanout remains a measured annotation."; close $f
close_design
exit
