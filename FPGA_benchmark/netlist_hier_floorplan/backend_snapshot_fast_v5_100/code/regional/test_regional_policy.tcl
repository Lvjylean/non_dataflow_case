source [file join [file dirname [info script]] policy.tcl]
source [file join [file dirname [info script]] regional_policy.tcl]
proc assert {value message} {if {![uplevel 1 [list expr $value]]} {error $message}}
proc pos {cr slr loc} {dict create cr $cr slr $slr loc $loc bel AFF}
set source [pos X3Y9 SLR2 SLICE_X90Y550]
set rows {}
for {set i 0} {$i < 31} {incr i} {
    set x [expr {$i % 6}]; set y [expr {$i < 16 ? 7 : 9}]
    set slr [expr {$i < 16 ? "SLR1" : "SLR2"}]
    lappend rows [list load${i}/I0 [pos X${x}Y${y} $slr SLICE_${i}]]
}
set root [rf::plan_root_reference memory/DOUT $source $rows]
assert {[dict get $root status] eq "selected"} "Spatial root not selected"
assert {[llength [dict get $root frontier]] == 6} "Expected six independent sectors"
foreach node [dict get $root nodes] {
    assert {[dict get $node kind] eq "source" && [dict get $node regions] eq "X3Y9"} "Source tier not near source"
    set sector [dict get $node destination_sector]
    foreach p [dict get $node loads] {
        set index [lsearch -index 0 -exact $rows $p]
        assert {[rf::sector [lindex [lindex $rows $index] 1]] eq $sector} "Mixed destination sectors"
    }
}
set corrupted $root
dict lappend corrupted frontier [lindex [dict get $root frontier] 0]
assert {[catch {rf::validate_tree $corrupted}]} "Duplicate edge accepted"
set rows {}
for {set i 0} {$i < 40960} {incr i} {
    set x [expr {($i/1024)%8}]; set y [expr {4+($i/8192)}]
    set slr [expr {$y < 8 ? "SLR1" : "SLR2"}]
    lappend rows [list data${i}/D [pos X${x}Y${y} $slr SLICE_${i}]]
}
set t [clock milliseconds]
set large [rf::plan_root_reference memory/DOUT $source $rows]
assert {[dict get $large status] eq "selected"} "Large tree not selected"
rf::validate_tree $large
puts "LOCAL_PLAN_40960_MS [expr {[clock milliseconds]-$t}]"
assert {[llength [dict get $large sinks]] == 40960} "Large coverage lost"
assert {[llength [dict get $large frontier]] <= 96} "Root cap exceeded"
set one {}
for {set i 0} {$i < 20} {incr i} {lappend one [list p$i/D [pos X1Y4 SLR1 SLICE_$i]]}
assert {[dict get [rf::plan_root_reference a/Q $source $one] status] eq "one_clock_region"} "Local root changed"
assert {![rf::allowed_driver RAMB36E2 SBITERR]} "RAM status accepted"
assert {[rf::allowed_driver RAMB36E2 {DOUTADOUT[3]}]} "RAM data excluded"
assert {![rf::has_fixed_route ""] && ![rf::has_fixed_route {{}}]} "Native empty route rejected"
assert {[rf::has_fixed_route {A {B C}}]} "Nonempty fixed route accepted"
assert {![rf::allowed_driver BUFGCE O]} "Clock buffer accepted"
assert {![rf::allowed_sink FDRE CE] && ![rf::allowed_sink FDRE C]} "Control sink accepted"
assert {[catch {rf::configure [dict create branch_limit 1]}]} "Nonprogressing fanout limit accepted"
puts "PASS: spatial sectors, source tier, exact coverage, 40960 sinks, duplicate rejection, data/clock scope"
