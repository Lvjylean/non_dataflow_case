source [file join [file dirname [info script]] policy.tcl]
source [file join [file dirname [info script]] regional_policy.tcl]
proc assert {value message} {if {![uplevel 1 [list expr $value]]} {error $message}}
proc pos {cr slr loc} {dict create cr $cr slr $slr loc $loc bel AFF}
set src [pos X4Y9 SLR2 SLICE_X1Y1]
set rows {}
for {set i 0} {$i < 96} {incr i} {lappend rows [list f96_identity_${i}/I0 [pos X[expr {$i%8}]Y9 SLR2 SLICE_$i]]}
assert {[dict get [rf::plan_root f96_identity_999/O $src $rows] status] eq "existing_fanout_sufficient"} "Legal existing tree acquired a new layer"
set rows {}
for {set i 0} {$i < 192} {incr i} {lappend rows [list sink$i/D [pos X3Y9 SLR2 SLICE_$i]]}
set root [rf::plan_root root/Q $src $rows]
assert {[dict get $root status] eq "selected"} "Over-limit single-CR net was not handled"
assert {[llength [dict get $root nodes]] == 2 && [llength [dict get $root frontier]] == 2} "Unnecessary source tier"
foreach node [dict get $root nodes] {
 assert {[dict get $node regions] eq "X3Y9" && [dict get $node movable]} "Node not placed at destination or locked"
 assert {[llength [dict get $node loads]]==96} "Incorrect electrical capacity"
}
set broken $root;dict lappend broken frontier [lindex [dict get $root frontier] 0]
assert {[catch {rf::validate_tree $broken}]} "Duplicate path accepted"
set rows {}
for {set i 0} {$i < 40960} {incr i} {
 set x [expr {($i/1024)%8}];set y [expr {4+($i/8192)}]
 lappend rows [list big$i/D [pos X${x}Y${y} [expr {$y<8?"SLR1":"SLR2"}] SLICE_$i]]
}
set t [clock milliseconds];set root [rf::plan_root root/Q $src $rows];rf::validate_tree $root
assert {[llength [dict get $root sinks]]==40960 && [llength [dict get $root frontier]]<=96} "Large coverage/cap violation"
foreach n [dict get $root nodes] {assert {[dict get $n kind] ne "source"} "Unconditional source stage remained"}
puts "SHALLOW_40960_MS [expr {[clock milliseconds]-$t}]"
set grid {}
for {set x 0} {$x<8} {incr x} {for {set y 0} {$y<16} {incr y} {dict set grid X${x}Y${y} SLR[expr {$y/4}]}}
set window [geo::window {X3Y9 X3Y9 X3Y9 X7Y11} $grid]
assert {$window eq "X2Y8 X2Y9 X2Y10 X3Y8 X3Y9 X3Y10 X4Y8 X4Y9 X4Y10"} "Weighted median window wrong"
set window [geo::window {X0Y8} $grid]
assert {$window eq "X0Y8 X0Y9 X1Y8 X1Y9"} "Device/SLR clipping wrong"
assert {[catch {geo::window {X0Y7 X0Y8} $grid}]} "Cross-SLR window accepted"
puts "PASS: legal-tree reuse, no source tier, destination windows, cap, exact leaves, locks, large tree and geometry"

assert {[geo::expand_ranges {CLOCKREGION_X2Y0:CLOCKREGION_X2Y1}] eq [geo::expand_ranges {CLOCKREGION_X2Y0:CLOCKREGION_X2Y0 CLOCKREGION_X2Y1:CLOCKREGION_X2Y1}]} "Normalized CR rectangle rejected"
assert {[geo::expand_ranges {CLOCKREGION_X2Y0:CLOCKREGION_X2Y2}] ne [geo::expand_ranges {CLOCKREGION_X2Y0:CLOCKREGION_X2Y1}]} "Expanded region escaped validation"
assert {[catch {geo::expand_ranges {SLICE_X0Y0:SLICE_X1Y1}}]} "Unexpected site-range type accepted"
puts "PASS: normalized multi-CR representation with exact spatial equality"
