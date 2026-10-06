set here [file dirname [file normalize [info script]]]
source $here/code/base/fanout96/core.tcl
source $here/code/base/fanout96/fast.tcl
if {$::f96::target != 96} {error "Incorrect base construction target"}
set rows {}
foreach count {80 95 96 97 98 99 100 101 199 200} {
 lappend rows [dict create sinks [lrepeat $count pin] count $count]
}
set result {}; foreach item [f96::required $rows] {lappend result [dict get $item count]}
if {$result ne {100 101 199 200}} {error "Strict acceptance boundary failed: $result"}
source $here/code/regional/policy.tcl
source $here/code/regional/regional_policy.tcl
if {[dict get $::rf::config branch_limit] != 96} {error "Incorrect regional target"}
rf::configure [dict create branch_limit 96]
if {![catch {rf::configure [dict create branch_limit 97]}]} {error "Out-of-policy branch target accepted"}
set lengths {}; foreach x [sb::chunks [lrepeat 400 pin] 99] {lappend lengths [llength $x]}
if {$lengths ne {99 99 99 99 4}} {error "CE chunks failed"}
puts "PASS: 99 accepted, 100 requires repair, base/regional target96, CE cap99"
