set_param general.maxThreads 4
open_checkpoint $::env(AUDIT_DCP)
foreach cell [get_cells -hier -filter {IS_PRIMITIVE == 0 && (NAME =~ *cnna_kernel_* || NAME =~ *vta64_kernel_*)}] {
  if {[regexp {(^|/)(cnna|vta64)_kernel_[0-9]+$} $cell]} {
    report_utilization -cells $cell -file [string map {/ _} $cell]_utilization.rpt
  }
}
report_cdc -details -show_waiver -file cdc_paths.rpt
exit
