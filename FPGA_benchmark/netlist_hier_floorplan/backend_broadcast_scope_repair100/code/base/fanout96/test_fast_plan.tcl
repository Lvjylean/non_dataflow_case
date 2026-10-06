# Pure Tcl tests for grouping invariants, independent of Vivado execution.
set here [file dirname [file normalize [info script]]]
source $here/core.tcl
source $here/fast.tcl
proc check {condition message} {if {![uplevel 1 [list expr $condition]]} {error $message}}
set f96::target 3
set pins {}
for {set i 0} {$i < 17} {incr i} {
    lappend pins c$i/D
    set f96::loc(c$i) SITE$i
    set f96::cr(c$i) [expr {$i < 9 ? "X0Y4" : "X0Y8"}]
    set f96::slr(c$i) [expr {$i < 9 ? "SLR1" : "SLR2"}]
}
lassign [f96::fast_plan $pins] plan frontier levels
check {[llength $frontier] <= 3 && $levels > 1} "Expected bounded multi-level tree"
set edges [dict create]
foreach entry $plan {
    lassign $entry name level hint group
    check {[llength $group] <= 3} "Oversized branch"
    dict set edges $name/I0 $group
}
set pending $frontier; set recovered {}
while {[llength $pending]} {
    set next {}
    foreach p $pending {
        if {[dict exists $edges $p]} {lappend next {*}[dict get $edges $p]} else {lappend recovered $p}
    }
    set pending $next
}
check {[lsort $recovered] eq [lsort $pins]} "Tree lost or duplicated original sink"
foreach c {a b} {set f96::loc($c) SAME_SITE; set f96::cr($c) X0Y4; set f96::slr($c) SLR1}
set result [f96::groups {a/R b/R a/CE b/CE} 0]
check {[llength $result] == 2} "Shared site split should use two role groups"
foreach entry $result {
    set g [lsort [lindex $entry 1]]
    check {$g in {{a/R b/R} {a/CE b/CE}}} "Shared reset/CE group split"
}
foreach c {d e} {set f96::loc($c) SAME_SITE; set f96::cr($c) X0Y4; set f96::slr($c) SLR1}
check {[catch {f96::groups {a/R b/R d/R e/R} 0}]} "Oversized shared reset must fail"
set test [list [dict create sinks [lrepeat 99 x]] [dict create sinks [lrepeat 100 x]]]
check {[llength [f96::required $test]] == 1} "Strictly below 100 stopping condition"
puts "PASS: multi-level coverage, bounded branches/root, shared reset/CE groups, oversized-group rejection, strict <100 stop"
