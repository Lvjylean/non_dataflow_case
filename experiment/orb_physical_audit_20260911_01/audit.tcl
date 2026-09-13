set_param general.maxThreads 2
cd $::env(AUDIT_DIR)
open_checkpoint $::env(SOURCE_RUN)/routed.dcp
source ../audit_fanout.tcl
fanout_scan final 1 0
set f [open verified.txt w]; puts $f [clock format [clock seconds]]; close $f
