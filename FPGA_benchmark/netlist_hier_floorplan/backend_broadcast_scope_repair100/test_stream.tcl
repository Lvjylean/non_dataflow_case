source [file join [file dirname [info script]] code/regional/core.tcl]
set folder [file join /tmp compilefast_save_test_[pid]]
file mkdir $folder
set plan [dict create schema test data [dict create {x[2]/a} {a;b $x [error injected]}] \
    multiline "a\nb\n" escaped {\ { } \\} empty {} many [lrepeat 1000 {a/b/c}]]
sb::save $plan $folder/plan.tcl
source $folder/plan.tcl
if {$sb_plan ne $plan} {error "Streamed plan roundtrip mismatch"}
if {[file exists $folder/plan.tcl.tmp]} {error "Incomplete atomic publication"}
file delete -force $folder
puts "PASS streamed plan exact roundtrip and safe quoting"
