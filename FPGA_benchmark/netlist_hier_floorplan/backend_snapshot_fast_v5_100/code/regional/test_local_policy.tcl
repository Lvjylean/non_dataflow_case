source [file join [file dirname [info script]] core.tcl]
source [file join [file dirname [info script]] local_policy.tcl]
proc check {value msg} {if {!$value} {error $msg}}
proc net {snapshotvar key pins {kind ordinary}} {
    upvar 1 $snapshotvar s
    dict set s nets $key [dict create kind $kind before $pins]
}
proc root {snapshotvar key ref inputs n} {
    upvar 1 $snapshotvar s
    dict set s roots $key [dict create ref $ref pin [lb::output_pin $ref] slr SLR0 inputs $inputs]
    set pins {}
    for {set i 0} {$i<$n} {incr i} {
        set p ${key}_load$i/D; lappend pins $p
        dict set s pin_slrs $p SLR[expr {$i%2}]
    }
    net s $key $pins
}
set c [dict create key CLOCK kind clock slr ""]
set r [dict create key RESET kind ordinary slr SLR0]
set d [dict create key logic/O kind ordinary slr SLR0]
set q [dict create key state/Q kind ordinary slr SLR0]
set s [dict create roots {} nets {} pin_slrs {}]
root s state/Q FDRE [dict create D $d C $c R $r CE [dict create key ONE kind constant slr ""]] 32
root s logic/O LUT2 [dict create I0 $q I1 [dict create key ZERO kind constant slr ""]] 32
# A state feedback cone crosses two SLRs; both origins and copies must remain coherent.
dict set s nets state/Q before [concat [dict get $s nets state/Q before] {logic/I0}]
dict set s nets logic/O before [concat [dict get $s nets logic/O before] {state/D}]
dict set s pin_slrs logic/I0 SLR0; dict set s pin_slrs state/D SLR0
net s RESET {state/R}; net s CLOCK {} clock; net s ONE {} constant; net s ZERO {} constant
set p [lb::select $s]
check [expr {[dict size [dict get $p graph replicas]]==2}] "Expected both FF and LUT copies"
set fc [dict get $p copies state/Q SLR1]; set lc [dict get $p copies logic/O SLR1]
check [expr {[dict get $p graph new_inputs $fc/D] eq "$lc/O"}] "FF copy must use local LUT copy"
check [expr {[dict get $p graph new_inputs $lc/I0] eq "$fc/Q"}] "LUT copy must use local state copy"
check [expr {[dict get $p graph new_inputs $fc/R] eq "RESET"}] "Dynamic reset preserved"
check [expr {[dict get $p graph new_inputs $fc/C] eq "CLOCK"}] "Clock preserved"
check [expr {[dict get $p graph expected logic/O] eq [lsort [concat [lsearch -all -inline -glob [dict get $s nets logic/O before] {*load*[02468]/D}] state/D]]}] "Original FF feedback preserved"
check [expr {[dict get $p graph new_inputs $lc/I1] eq "ZERO"}] "LUT truth-table input constant preserved"
foreach {ref pin} {LUT4 O MUXF8 O FDSE Q RAMB36E2 {DOUTADOUT[0]}} {check [lb::input_source $ref $pin] "Expanded D source $ref/$pin"}
foreach {ref pin} {LUT3 I2 FDRE CE FDSE S RAMB36E2 {DINBDIN[3]} RAMB36E2 {WEBWE[7]} URAM288 {ADDR_A[3]} MUXF8 S} {check [lb::ordinary_input $ref $pin] "Expanded sink $ref/$pin"}
foreach {ref pin} {FDCE CLR FDRE C RAMB36E2 CLKBWRCLK URAM288 CLK} {check [expr {![lb::ordinary_input $ref $pin]}] "Special sink must stay excluded"}
# Three replicas share an upstream net already at fanout 98: only one may add a load.
set s [dict create roots {} nets {} pin_slrs {}]
set before {}; for {set i 0} {$i<95} {incr i} {lappend before other$i/D}
for {set i 0} {$i<3} {incr i} {
    root s ff$i/Q FDRE [dict create D [dict create key upstream/O kind ordinary slr SLR0]] 32
    lappend before ff$i/D
}
net s upstream/O $before
set p [lb::select $s]
check [expr {[dict size [dict get $p graph replicas]]==1}] "Global upstream cap must reject two copies"
check [expr {[llength [dict get $p graph expected upstream/O]]==99}] "Upstream fanout cap"
check [expr {[lb::select $s] eq $p}] "Deterministic planning"
set failed 0
set key ff0/Q; set pins [dict get $s nets $key before]
dict set s nets $key before [concat $pins [lindex $pins 0]]
if {[catch {lb::select $s}]} {set failed 1}
check $failed "Duplicate input graph must fail"
puts "PASS local graph: joint state/logic feedback, dynamic reset, source/sink expansion, special exclusions, global cap, deterministic complete sink mapping"

set s [dict create roots {} nets {} pin_slrs {}]
root s big/Q FDRE {} 220
set p [lb::select $s]
check [expr {[dict size [dict get $p graph replicas]]==0}] "Oversized target group must be rejected without aborting discovery"
source [file join [file dirname [info script]] regional.tcl]
source [file join [file dirname [info script]] local_broadcast.tcl]
lb::install
foreach cmd {::sb::scan ::sb::apply ::sb::verify ::sb::reports ::rf::legacy_exclusions} {
    check [expr {[llength [info commands $cmd]]==1}] "Global wrapper missing: $cmd"
}
check [expr {![namespace exists ::lb::sb]}] "Wrappers must not move into a nested namespace"
puts "PASS native entry wrappers and oversized target admission"

set s [dict create roots {} nets {} pin_slrs {}]
root s selected/Q FDRE {} 32
root s too_big/Q FDRE {} 220
set p [lb::edit_scope [lb::select $s]]
check [expr {![dict exists $p snapshot nets too_big/Q]}] "Rejected unrelated root must remain available to regional processing"
check [expr {[dict size [dict get $p graph moves]]==16}] "Scoped graph must preserve every accepted rewrite"
puts "PASS disjoint edit certificate scope"

set out [file join /tmp local_plan_host_[pid]]; file mkdir $out
set expected [lb::edit_scope [lb::select $s]]
set observed [lb::host_plan $s $out 16]
check [expr {$observed eq $expected}] "Host execution must preserve the exact pure graph result"
file delete -force $out
puts "PASS host planner exact equivalence"
