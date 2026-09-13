report_route_status -file route_status.rpt
report_utilization -file utilization.rpt
report_utilization -hierarchical -hierarchical_depth 5 -file utilization_hierarchical.rpt
report_timing_summary -delay_type min_max -report_unconstrained -max_paths 20 -file timing_summary.rpt
report_timing -delay_type max -max_paths 100 -path_type full_clock_expanded -file setup_paths.rpt
report_timing -delay_type min -max_paths 20 -file hold_paths.rpt
report_drc -file drc.rpt
report_methodology -file methodology.rpt
report_clock_utilization -file clock_utilization.rpt
# Optional diagnostic reports must not invalidate a successfully routed checkpoint.
foreach {name command} {
    congestion {report_design_analysis -congestion -file congestion.rpt}
    slr_crossings {report_design_analysis -slr_crossing -file slr_crossings.rpt}
    slr_utilization {report_utilization -slr -file slr_utilization.rpt}
} {
    if {[catch {eval $command} message]} {
        set f [open ${name}_unavailable.txt w]; puts $f $message; close $f
    }
}
set f [open metrics.tsv w]
puts $f "metric\tvalue"
foreach kind {max min} {
    set path [get_timing_paths -delay_type $kind -max_paths 1]
    puts $f "${kind}_slack_ns\t[get_property SLACK $path]"
}
puts $f "blackboxes\t[llength [get_cells -hier -filter {IS_BLACKBOX == 1}]]"
puts $f "drc_errors\t[llength [get_drc_violations -quiet -filter {SEVERITY == Error}]]"
puts $f "drc_critical_warnings\t[llength [get_drc_violations -quiet -filter {SEVERITY == {Critical Warning}}]]"
close $f
