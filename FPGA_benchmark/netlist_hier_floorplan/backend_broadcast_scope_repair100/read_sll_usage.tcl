# Read-only per-bundle routed resource inventory for the unchanged control DCP.
if {[catch {
    lassign $argv checkpoint out
    set_param general.maxThreads 4
    open_checkpoint $checkpoint
    source [file join [file dirname [info script]] sll_balance.tcl]
    sllph::assert_absent
    sllph::routed_usage $out
    close_design
    set f [open $out/PASS w]; puts $f PASS; close $f
    exit
} message options]} {puts stderr [dict get $options -errorinfo]; exit 1}
