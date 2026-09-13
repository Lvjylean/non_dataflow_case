set_param general.maxThreads 4
open_checkpoint $::env(AUDIT_DCP)
set ::env(SKIP_CHECKPOINT_WRITE) 1
source [file join [file dirname [info script]] platform_postroute.tcl]
set f [open $::env(BENCH_REPORT_DIR)/reopened.txt w]
puts $f "Independently reopened $::env(AUDIT_DCP)"
close $f
exit
