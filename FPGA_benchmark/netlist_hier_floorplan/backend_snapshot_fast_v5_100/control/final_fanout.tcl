set ::experiment_fanout_root [file normalize [file join [file dirname [info script]] ..]]
proc experiment_final_fanout {out} {
    set source_root $::experiment_fanout_root
    source $source_root/code/base/fanout96/core.tcl
    set start [clock milliseconds]
    set selected [f96::scan $out/fanout_final 0]
    set residual 0
    foreach item $selected {if {[llength [dict get $item sinks]] >= 100} {incr residual}}
    set f [open $out/fanout_acceptance.tsv w]
    puts $f "metric\tvalue"
    puts $f "ordinary_ge100\t$residual"
    puts $f "internal_branch_target\t96"
    puts $f "ordinary_required_lt\t100"
    puts $f "scan_elapsed_ms\t[expr {[clock milliseconds]-$start}]"
    close $f
}
