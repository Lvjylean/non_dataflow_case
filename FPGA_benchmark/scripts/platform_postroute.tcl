set output $::env(BENCH_REPORT_DIR)
set report_script_dir [file normalize [file dirname [info script]]]
if {![file exists [file join $report_script_dir reports.tcl]]} {
  set report_script_dir [file join $::env(BENCH_ROOT) scripts]
}
file mkdir $output
set previous [pwd]
cd $output
if {![info exists ::env(SKIP_CHECKPOINT_WRITE)]} {write_checkpoint -force routed.dcp}
if {[info exists ::env(FAST_REOPEN)]} {
  source [file join $report_script_dir reports_reopen.tcl]
} else {
  source [file join $report_script_dir reports.tcl]
}
report_clocks -file clocks.rpt
check_timing -verbose -file check_timing.rpt
report_cdc -file cdc.rpt
if {[info exists ::env(FAST_REOPEN)]} {
  report_cdc -details -show_waiver -file cdc_paths.rpt
}
report_exceptions -file exceptions.rpt
set f [open route_flags.tsv w]
puts $f "flag\tvalue"
foreach flag {PLACED_FULLY PARTIALLY_ROUTED ROUTED_FULLY ERRORS_IN_ROUTES} {puts $f "$flag\t[report_route_status -boolean_check $flag]"}
foreach flag {GAPS PARTIAL UNROUTED CONFLICTS} {puts $f "$flag\t[llength [report_route_status -return_nets -route_type $flag]]"}
close $f
set kernels {}
foreach cell [get_cells -hier -filter {IS_PRIMITIVE == 0 && (NAME =~ *cnna_kernel_* || NAME =~ *vta64_kernel_*)}] {
  if {[regexp {(^|/)(cnna|vta64)_kernel_[0-9]+$} $cell]} {lappend kernels $cell}
}
if {[llength $kernels] == 0} {error "No accelerator hierarchy found"}
set f [open accelerator_regions.tsv w]
puts $f "kernel\tslr\tprimitive_count"
foreach kernel $kernels {
  report_utilization -cells $kernel -file [string map {/ _} $kernel]_utilization.rpt
}
foreach slr [get_slrs] {
    set sites [get_sites -of_objects [get_clock_regions -of_objects $slr]]
    set objects [get_cells -quiet -of_objects $sites]
    set site_cells [get_property NAME $objects]
  foreach kernel $kernels {
    set count 0
    foreach cell $site_cells {
      if {[string match "$kernel/*" $cell]} {
        incr count
      }
    }
    puts $f "$kernel\t$slr\t$count"
  }
}
close $f
cd $previous
