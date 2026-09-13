set_param general.maxThreads 4
open_checkpoint ../routed.dcp
source $::env(BENCH_ROOT)/scripts/reports.tcl
set f [open reopened.txt w]; puts $f "Independent Vivado process reopened routed.dcp and regenerated reports"; close $f
exit
