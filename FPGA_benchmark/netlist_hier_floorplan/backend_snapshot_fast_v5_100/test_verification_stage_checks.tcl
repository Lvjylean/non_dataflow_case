# Reuse the original verification fixtures, then compare the complete checker
# reports and errors with a shared read-only context enabled.
set here [file dirname [file normalize [info script]]]
source $here/test_pblock_verify_cache.tcl
set out [file join /tmp verification_stage_checks_[pid]]
file mkdir $out
set stage_cases 0
proc compare_context {label mutation {placed 1} {failure ""}} {
    global out plan stage_cases
    fixture; uplevel #0 $mutation
    set reference [run slow [file join $out $label reference] $placed]
    set actual [vs::with $label {run fast [file join $out $label cached] $placed}]
    foreach key {code result files parents} {
        sb::require [expr {[dict get $reference $key] eq [dict get $actual $key]}] "Changed checker decision/evidence: $label/$key"
    }
    if {$failure ne ""} {
        sb::require [expr {[dict get $actual code] == 1 && [string first $failure [dict get $actual result]] >= 0}] "Missing failure: $label"
    } else {sb::require [expr {[dict get $actual code] == 0}] "Unexpected rejection: $label"}
    incr stage_cases
}
compare_context placed {}
compare_context unplaced {} 0
compare_context config {set {configs(copy[22])} {INIT 1'b1}} 1 {Replica function mismatch}
compare_context missing_members {set members(child_hint) {};set {assigned(copy[23])} {}} 1 {Replica missing from SLR Pblock}
compare_context protection {set {props(copy[22],DONT_TOUCH)} 0} 1 {Replica unprotected}
compare_context exact_lock {set {props(copy[22],IS_LOC_FIXED)} 1} 1 {Replica acquired exact location lock}
compare_context soft_slr {set props(localrep_SLR1,IS_SOFT) 1} 1 {Missing hard replica SLR Pblock}
compare_context slr {dict set {positions(copy[22])} slr SLR3} 1 {Replica outside target SLR}
compare_context connectivity {set {actual_sinks(copy[22]/Q)} another/D} 1 {Local output sink mismatch}
compare_context floorplan {lappend members(user_pb) extra_member} 1 {Original floorplan changed}
compare_context hint {set props(child_hint,GRID_RANGES) wrong} 1 {Joint soft region changed}
compare_context unknown_protection {unset {props(copy[22],DONT_TOUCH)}} 1 {Missing property}
# A second full checker in the same immutable stage executes every rule and
# produces the same evidence while reusing actual membership/property reads.
fixture
vs::begin repeated_checkers
set first [run fast [file join $out repeated first] 1]
set second [run fast [file join $out repeated second] 1]
set metrics [vs::end]
foreach key {code result files parents} {
    sb::require [expr {[dict get $first $key] eq [dict get $second $key]}] "Repeated checker evidence changed: $key"
}
sb::require [expr {[dict size [dict get $first queries]] > 0 && [dict size [dict get $second queries]] == 0}] "Native membership was not reused across checkers"
sb::require [expr {[dict get $metrics query_hits] > 0 && [dict get $metrics property_hits] > 0}] "Shared context had no cache reuse"
# The following independent stage must inspect newly changed membership.
set members(localrep_SLR0) [lrange $members(localrep_SLR0) 0 end-1]
set {assigned(copy[22])} {}
set next [vs::with independent_reopen {run fast [file join $out repeated reopened] 1}]
sb::require [expr {[dict get $next code] == 1 && [dict get $next result] eq "Replica missing from SLR Pblock"}] "Stale membership survived an independent verification"
sb::require [expr {[dict size [dict get $next queries]] > 0}] "Next stage did not read live membership"
file delete -force $out
puts "PASS: $stage_cases native/reference vs context checker cases, exact report/error equivalence, repeated checks reused native reads, independent-stage freshness"
