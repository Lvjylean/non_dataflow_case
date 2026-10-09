# Integration audit on an immutable GETRF checkpoint; no full routing is run here.
if {[catch {
lassign $argv code input out mode plan_file
if {[file exists $out]} {error "Refusing to overwrite $out"}
file mkdir $out
source $code/checkpoint_io.tcl
source $code/code/regional/core.tcl
source $code/code/regional/regional.tcl
source $code/code/regional/local_broadcast.tcl
lb::install
execopt::configure fast
set_param general.maxThreads 8
set begin [clock milliseconds]
open_checkpoint $input
if {$mode eq "reopen"} {
    source $plan_file
    sb::verify $sb_plan $out 0
} else {
    if {$mode eq "planned"} {
        set f [open $plan_file r]; eval [read $f]; close $f
        set plan [lb::planned_plan $lb_local 16]
    } else {set plan [sb::scan $out 1000 16]}
    set plan [sb::apply $plan $out]
    sb::verify $plan $out/after_edit 0
    write_checkpoint $out/after_edit.dcp
    set f [open $out/counts.tsv w]; puts $f "ff_added\tlut_added\tmoved_original_pins\tnew_inputs\tcertified_nets"
    set g [dict get $plan local_broadcast graph]
    puts $f "[dict get $plan ff_added]\t[dict get $plan lut_added]\t[dict size [dict get $g moves]]\t[dict size [dict get $g new_inputs]]\t[dict size [dict get $g expected]]"; close $f
}
execopt::save $out $mode
set f [open $out/PASS w]; puts $f "PASS connectivity/configuration/SLR region constraints; unplaced new replicas, no new routing or WNS claim; elapsed_ms=[expr {[clock milliseconds]-$begin}]"; close $f
close_design
exit
} message options]} {puts stderr [dict get $options -errorinfo]; exit 1}
