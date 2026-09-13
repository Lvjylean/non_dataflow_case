# Reproduce acceptance evidence; presentation-only reports remain in the first audit.
report_route_status -file route_status.rpt
report_timing_summary -delay_type min_max -report_unconstrained -max_paths 20 -file timing_summary.rpt
report_drc -file drc.rpt
set f [open metrics.tsv w]
puts $f "metric\tvalue"
foreach kind {max min} {
  set paths [get_timing_paths -delay_type $kind -max_paths 1]
  if {[llength $paths] == 0} {error "No timed $kind path"}
  puts $f "${kind}_slack_ns\t[get_property SLACK $paths]"
}
puts $f "blackboxes\t[llength [get_cells -hier -filter {IS_BLACKBOX == 1}]]"
puts $f "drc_errors\t[llength [get_drc_violations -quiet -filter {SEVERITY == Error}]]"
puts $f "drc_critical_warnings\t[llength [get_drc_violations -quiet -filter {SEVERITY == {Critical Warning}}]]"
close $f
report_methodology -file methodology.rpt
