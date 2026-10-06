source [file join [file dirname [info script]] joint_input.tcl]
namespace eval sb {}
proc sb::require {ok message} {if {!$ok} {error $message}}
set before {real0/D real1/D real2/I0 sbeco_real_existing/I0}
set snapshot [dict create nets [dict create source/Q [dict create before $before]] \
    pin_slrs {real0/D SLR0 real1/D SLR1 real2/I0 SLR1 sbeco_real_existing/I0 SLR1}]
set local [dict create snapshot $snapshot graph [dict create expected [dict create \
    copy/Q {real1/D real2/I0 sbeco_real_existing/I0 planned_lut/I0 planned_ff/CE}]]]
set actual [ji::placed_loads $local source/Q SLR1]
sb::require [expr {$actual eq {real1/D real2/I0 sbeco_real_existing/I0}}] "Planned replica input leaked into placed receivers"
sb::require [expr {[llength $actual]==3}] "New inputs must be budgeted separately, not subtracted from original fanout"
sb::require [expr {[ji::placed_loads $local source/Q SLR0] eq {real0/D}}] "Wrong target SLR"
sb::require [catch {ji::placed_loads $local source/Q SLR2} message] "Empty candidate must fail closed"
sb::require [string match {No placed receivers*} $message] "Unexpected empty-group error"
dict unset local snapshot pin_slrs real2/I0
sb::require [catch {ji::placed_loads $local source/Q SLR1}] "Incomplete placement metadata must not be skipped"
puts {PASS joint placed receiver positions and load accounting}
