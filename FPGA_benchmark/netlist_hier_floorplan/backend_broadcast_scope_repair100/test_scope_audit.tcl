set here [file dirname [file normalize [info script]]]
namespace eval lb {};namespace eval ji {};namespace eval sb {}
proc load_proc {path marker} {
 set f [open $path];set s [read $f];close $f
 set start [string first $marker $s];set end [string first "\nproc " $s [expr {$start+1}]]
 if {$end<0} {set end [string length $s]}
 uplevel #0 [string range $s $start [expr {$end-1}]]
}
load_proc $here/code/regional/local_broadcast.tcl {proc lb::scope_audit }
load_proc $here/code/regional/joint_input.tcl {proc ji::hint_constraints }
proc sb::cell {name} {return $name}
proc sb::names {items} {return $items}
proc sb::require {ok why} {if {!$ok} {error $why}}
proc get_property {prop obj} {return $::prop($obj,$prop)}
proc get_pblocks {name} {return $name}
proc get_sites {args} {return [lindex $args end]}
proc get_slrs {args} {return $::actual([lindex $args end])}
proc lb::bind {name slr} {set ::prop($name,PBLOCK) localrep_$slr;set ::prop(localrep_$slr,GRID_RANGES) $slr}
proc write_checkpoint {args} {incr ::checkpoints;set f [open [lindex $args end] w];puts $f DIAGNOSTIC;close $f}
set local [dict create joint_input [dict create hints [dict create a {slr SLR0 x 3 y 3} b {slr SLR1 x 4 y 4}]]]
set local [ji::hint_constraints $local]
if {$::prop(a,PBLOCK) ne "localrep_SLR0" || $::prop(b,PBLOCK) ne "localrep_SLR1" || [dict get $local joint_input hints a binding] ne "hard_slr_only"} {error "Hard binding lost"}
set plan [dict create local_broadcast [dict create graph [dict create replicas [dict create a {slr SLR0} b {slr SLR1} c {slr SLR0}]]]]
foreach n {a b c} {set ::prop($n,LOC) SLICE_$n;set ::prop($n,BEL) AFF;set ::prop($n,PBLOCK) localrep_SLR0}
set actual(a) SLR1;set actual(b) SLR0;set actual(c) SLR0
set out [file join /tmp scope_audit_[pid]];file mkdir $out;set ::checkpoints 0
set code [catch {lb::scope_audit $plan $out} why]
if {$code!=1 || $::checkpoints!=1 || [string first {(2)} $why]<0} {error "Multiple violations not captured"}
set f [open $out/replica_scope_all.tsv];set rows [split [string trim [read $f]] \n];close $f
if {[llength $rows]!=4} {error "Audit stopped before all replicas"}
set actual(a) SLR0;set actual(b) SLR1
lb::scope_audit $plan $out
if {$::checkpoints!=1} {error "Passing audit wrote an unnecessary DCP"}
file delete -force $out
puts "PASS hard direct SLR binding, complete multi-failure evidence, checkpoint-on-failure only"
