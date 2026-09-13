set_param general.maxThreads 4
open_checkpoint $::env(AUDIT_DCP)
set f [open route_flags.tsv w]
puts $f "flag\tvalue"
foreach flag {PLACED_FULLY PARTIALLY_ROUTED ROUTED_FULLY ERRORS_IN_ROUTES} {
 puts $f "$flag\t[report_route_status -boolean_check $flag]"
}
foreach status {GAPS PARTIAL UNROUTED CONFLICTS} {
 set nets [report_route_status -return_nets -route_type $status]
 puts $f "$status\t[llength $nets]"
 set g [open ${status}_nets.txt w]
 foreach net $nets {puts $g $net}
 close $g
 if {[llength $nets]} {report_route_status -of_objects $nets -file ${status}_detail.rpt}
}
close $f
set sources [all_registers -output_pins]
set sinks [all_registers -data_pins]
set f [open internal_timing.tsv w]
puts $f "metric\tvalue"
foreach kind {max min} {
 set path [get_timing_paths -from $sources -to $sinks -delay_type $kind -max_paths 1]
 puts $f "${kind}_slack_ns\t[get_property SLACK $path]"
 report_timing -from $sources -to $sinks -delay_type $kind -max_paths 10 -file internal_${kind}_timing.rpt
}
close $f
exit
