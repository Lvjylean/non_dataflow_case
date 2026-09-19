set_param general.maxThreads 8
lassign $argv input checkpoint out
if {[file exists $out]} {error "Refusing to replace readback evidence"}
file mkdir $out
set here [file dirname [file normalize [info script]]]
source $here/../fanout96/core.tcl
source $here/../connection_floorplan/audit.tcl
source $here/adapter.tcl
bi_load $input
open_checkpoint $checkpoint
f96::phase reopened
report_timing_summary -delay_type min_max -file $out/timing_summary.rpt
report_route_status -file $out/route_status.rpt
report_utilization -slr -file $out/utilization_slr.rpt
set geometry [bi_geometry $out/geometry]
cf_audit_regions $out/regions
f96::spatial_cache
set helpers [get_cells -quiet f96_identity_*]; set bad 0
foreach init [f96::values INIT $helpers] dt [f96::values DONT_TOUCH $helpers] {
    if {$init ne "2'h2" || !$dt} {incr bad}
}
set roots [get_nets -segments -of_objects [get_pins -of_objects $helpers -filter {DIRECTION == IN}]]
set unprotected 0
foreach flag [f96::values DONT_TOUCH $roots] {if {!$flag} {incr unprotected}}
set f [open $out/identity_summary.tsv w]
puts $f "helpers\tbad_init_or_unprotected\tregisters\tinput_segments\tunprotected_input_segments"
puts $f "[llength $helpers]\t$bad\t[llength [get_cells -hier -filter {IS_PRIMITIVE == 1 && REF_NAME =~ FD*}]]\t[llength $roots]\t$unprotected"; close $f
set f [open $out/worst_path_endpoints.tsv w]
puts $f "startpoint\tendpoint\tslack\tstart_slr\tend_slr\tstart_cr\tend_cr"
foreach path [get_timing_paths -delay_type max -max_paths 1000 -nworst 1000 -unique_pins] {
    set start [get_property STARTPOINT_PIN $path]; set end [get_property ENDPOINT_PIN $path]
    puts $f "$start\t$end\t[get_property SLACK $path]\t[f96::region_of $start 1]\t[f96::region_of $end 1]\t[f96::region_of $start 0]\t[f96::region_of $end 0]"
}
close $f
set residual [f96::scan $out/fanout 1]
set f [open $out/complete.txt w]
puts $f "Readback complete; geometry_failures=$geometry; identity_failures=$bad; unprotected=$unprotected. Logical scan covers live candidates; full all-net physical certificate not run."; close $f
close_design
f96::phase complete
exit
