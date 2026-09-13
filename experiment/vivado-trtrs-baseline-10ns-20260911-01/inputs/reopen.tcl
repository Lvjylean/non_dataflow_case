cd $::env(RUN_DIR)
set_param general.maxThreads 4
open_checkpoint routed.dcp
file mkdir reopen
cd reopen
source ../inputs/reports.tcl
set f [open verified.txt w]; puts $f [clock format [clock seconds]]; close $f
