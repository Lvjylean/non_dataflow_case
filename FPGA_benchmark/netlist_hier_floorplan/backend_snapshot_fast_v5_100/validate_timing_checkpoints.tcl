# Read-only full GETRF endpoint replay against archived original timing tables.
if {[catch {
lassign $argv code reference out
file mkdir $out
source $code/code/regional/core.tcl
source $code/code/regional/joint_input.tcl
set_param general.maxThreads 8
foreach stage {before placed} relative {base/pre_route.dcp generic/implementation/post_place.dcp} folder {joint_before joint_placed} {
    set checkpoint $reference/$relative;set target $out/$stage;file mkdir $target
    set start [clock microseconds]
    open_checkpoint $checkpoint
    set opened [clock microseconds]
    set f [open $reference/generic/implementation/$folder/slacks.tsv];gets $f header;set pins {}
    while {[gets $f line]>=0} {if {$line ne ""} {lappend pins [lindex [split $line \t] 0]}}
    close $f
    jif::guard_slacks $pins $target/slacks.tsv
    set checked [clock microseconds]
    exec python3 $code/compare_timing_slacks.py $reference/generic/implementation/$folder/slacks.tsv $target/slacks.tsv $target/comparison.json
    report_timing_summary -delay_type min_max -file $target/timing_summary.rpt
    set f [open $target/elapsed.tsv w];puts $f "phase\tseconds"
    puts $f "open\t[expr {($opened-$start)/1e6}]\ncheck\t[expr {($checked-$opened)/1e6}]\nreport_and_compare\t[expr {([clock microseconds]-$checked)/1e6}]";close $f
    close_design
}
set f [open $out/PASS w];puts $f "PASS complete original endpoint set, setup/hold presence and numerical equality";close $f
} message options]} {puts stderr [dict get $options -errorinfo];exit 1}
exit 0
