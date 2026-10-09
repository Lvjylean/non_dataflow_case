source [file join [file dirname [info script]] code regional verification_snapshot.tcl]
# Execute the original and accelerated verification procedures with the same
# read-only object model. No Vivado process or design is modified by this test.
set here [file dirname [file normalize [info script]]]
set old [file join $here test_reference local_broadcast_original.tcl]
set expected_original_sha256 452e5145009ce4fa25307ceb326fea73b93a4e88c323f0c344767603089dc976
set observed_original_sha256 [exec python3 -c {import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())} $old 2>@stderr]
if {$observed_original_sha256 ne $expected_original_sha256} {error "Original production test reference changed"}
set new [file join $here code regional local_broadcast.tcl]
proc load_definition {path name target_namespace} {
    set f [open $path]; set text [read $f]; close $f
    set begin [string first "proc lb::$name " $text]
    if {$begin < 0} {error "Missing production definition: $name"}
    set end [string first "\nproc " $text [expr {$begin+1}]]
    if {$end < 0} {set end [string length $text]}
    set definition [string range $text $begin [expr {$end-1}]]
    namespace eval $target_namespace {}
    uplevel #0 [string map [list "proc lb::$name " "proc ${target_namespace}::$name "] $definition]
}
foreach ns {slow fast} path [list $old $new] {
    foreach name {pblock_snapshot verify} {load_definition $path $name $ns}
    proc ${ns}::log {message} {}
    proc ${ns}::source_net {local key} {return $key}
}
# Isolate membership-cache equivalence from the separately tested scope audit.
proc fast::scope_audit {plan out} {}
load_definition $new pblock_member_names fast
load_definition $new verification_prefetch fast
namespace eval sb {}
namespace eval ji {}
proc sb::require {ok why} {if {!$ok} {error $why}}
proc sb::spatial_cache {} {}
# This fixture isolates Pblock verification; full typed prefetch is exercised
# with the native object model in test_verification_typed_prefetch.tcl.
proc sb::verification_prefetch {args} {}
proc sb::names {objects {native_class {}}} {return $objects}
proc sb::cell {name} {return $name}
proc sb::ref {name} {global refs; return $refs($name)}
proc sb::config {name} {global configs; return $configs($name)}
proc sb::signal {pin} {global signals; return $signals($pin)}
proc sb::one_bit {value} {return [expr {$value in {1 true TRUE}}]}
proc sb::counts {} {return {mux 0}}
proc sb::position {cell} {global positions; return $positions($cell)}
proc ji::in_parent {cell parent} {
    global child_parent assigned parent_checks
    lappend parent_checks $cell
    foreach pb $assigned($cell) {
        set seen {}
        while {$pb ne "" && $pb ne "ROOT" && $pb ni $seen} {
            if {$pb eq $parent} {return 1}
            lappend seen $pb; set pb $child_parent($pb)
        }
    }
    return 0
}
proc get_property {key object} {
    global props
    if {$key eq "CLASS"} {
        set values {};foreach obj $object {
            if {[info exists props($obj,GRID_RANGES)]} {lappend values pblock} elseif {[string first / $obj]>=0} {lappend values pin} else {lappend values cell}
        }
        if {[llength $object]==1} {return [lindex $values 0]};return $values
    }
    if {[llength $object] != 1} {error "Unexpected scalar property query: $key $object"}
    set object [lindex $object 0]
    if {![info exists props($object,$key)]} {error "Missing property: $object.$key"}
    return $props($object,$key)
}
proc get_pblocks {args} {
    global pb_order
    set requested [lindex $args end]
    if {$requested eq "*"} {return $pb_order}
    if {$requested in $pb_order} {return [list $requested]}
    return {}
}
proc get_cells {args} {
    global members queries
    if {[lrange $args 0 1] ne {-quiet -of_objects}} {error "Unexpected cell query: $args"}
    set pb [lindex $args 2]
    if {![info exists queries($pb)]} {set queries($pb) 0}
    incr queries($pb)
    return $members($pb)
}
proc get_nets {args} {return [lindex $args end]}
proc get_pins {args} {
    global actual_sinks
    set i [lsearch -exact $args -of_objects]
    return $actual_sinks([lindex $args [expr {$i+1}]])
}
proc fixture {} {
    global props members queries refs configs positions signals assigned child_parent
    global actual_sinks pb_order parent_checks plan
    foreach a {props members queries refs configs positions signals assigned child_parent actual_sinks} {
        upvar 0 $a values; array unset values *
    }
    set parent_checks {}; set pb_order {user_pb localrep_SLR0 localrep_SLR1 child_hint}
    set members(user_pb) {root unrelated_cell}
    set members(localrep_SLR0) {}; set members(localrep_SLR1) {}; set members(child_hint) {}
    foreach pb $pb_order {
        set props($pb,NAME) $pb
        set props($pb,IS_SOFT) [expr {$pb in {user_pb child_hint}}]
        set props($pb,GRID_RANGES) {CLOCKREGION_X1Y1:CLOCKREGION_X2Y2}
        set props($pb,PARENT) ROOT; set child_parent($pb) ROOT
    }
    set props(child_hint,PARENT) localrep_SLR1; set child_parent(child_hint) localrep_SLR1
    set refs(root) FDRE; set configs(root) {INIT 1'b0}
    set signals(root/D) {drivers upstream/Q}
    set root [dict create cell root ref FDRE config $configs(root) pin Q inputs {D {key upstream/Q}}]
    set graph [dict create replicas {} moves {} new_inputs {} expected {}]
    set hints {}
    for {set i 0} {$i<24} {incr i} {
        set name [format {copy[%d]} $i]; set slr SLR[expr {$i%2}]
        dict set graph replicas $name [dict create key root/Q slr $slr]
        dict set graph new_inputs $name/D upstream/Q
        set signals($name/D) {drivers upstream/Q}
        set sink [format {sink[%d]/D} $i]
        dict set graph expected $name/Q [list $sink]
        set actual_sinks($name/Q) [list $sink]
        set refs($name) FDRE;set configs($name) $configs(root)
        foreach {key value} {IS_LOC_FIXED 0 IS_BEL_FIXED 0 DONT_TOUCH 1} {set props($name,$key) $value}
        set positions($name) [dict create slr $slr loc SLICE_X0Y$i bel AFF]
        set positions([file dirname $sink]) [dict create slr $slr loc SLICE_X1Y$i bel BFF]
        set assigned($name) [list localrep_$slr]
        if {$i==23} {
            lappend members(child_hint) $name;set assigned($name) {child_hint}
            dict set hints $name [dict create pblock child_hint ranges $props(child_hint,GRID_RANGES)]
        } else {lappend members(localrep_$slr) $name}
    }
    set original [dict create user_pb [dict create ranges $props(user_pb,GRID_RANGES) soft 1 members [lsort $members(user_pb)]]]
    set snapshot [dict create roots [dict create root/Q $root] nets {upstream/Q {signal {drivers upstream/Q}}}]
    set local [dict create snapshot $snapshot graph $graph original_pblocks $original joint_input [dict create hints $hints]]
    set plan [dict create local_broadcast $local counts_before {mux 0}]
}
proc run {kind out placed} {
    global plan queries parent_checks
    array unset queries *; set parent_checks {}
    set old_channels [file channels]
    set code [catch {${kind}::verify $plan $out $placed} result]
    foreach ch [file channels] {if {$ch ni $old_channels} {close $ch}}
    set files {}
    foreach p [lsort [glob -nocomplain $out/*]] {
        set f [open $p]; dict set files [file tail $p] [read $f]; close $f
    }
    return [dict create code $code result $result files $files queries [array get queries] parents $parent_checks]
}
set out [file join /tmp verify_pblock_cache_[pid]]
file mkdir $out
set case_count 0
proc compare_case {label mutation {placed 1} {expect_failure ""}} {
    global out case_count plan
    fixture; uplevel #0 $mutation
    set before [run slow [file join $out $label old] $placed]
    set after [run fast [file join $out $label new] $placed]
    foreach key {code result files parents} {
        sb::require [expr {[dict get $before $key] eq [dict get $after $key]}] "Non-equivalent $label/$key"
    }
    if {$expect_failure eq ""} {
        sb::require [expr {[dict get $after code]==0}] "Unexpected rejection: $label"
    } else {
        sb::require [expr {[dict get $after code]==1 && [string first $expect_failure [dict get $after result]]>=0}] "Missing rejection: $label"
    }
    dict for {pb count} [dict get $after queries] {sb::require [expr {$count==1}] "Repeated membership lookup: $label/$pb/$count"}
    incr case_count
    return [list $before $after]
}
lassign [compare_case placed {}] slow_result fast_result
sb::require [expr {[dict get $slow_result queries localrep_SLR0]==13 && [dict get $fast_result queries localrep_SLR0]==1}] "Hotspot was not exercised"
sb::require [expr {[dict get $fast_result parents] eq {{copy[23]}}}] "Nested child membership not checked"
compare_case unplaced {} 0
compare_case missing_last {set members(child_hint) {};set {assigned(copy[23])} {}} 1 {Replica missing from SLR Pblock}
compare_case soft_parent {set props(localrep_SLR1,IS_SOFT) 1} 1 {Missing hard replica SLR Pblock}
compare_case exact_lock {set {props(copy[22],IS_LOC_FIXED)} 1} 1 {Replica acquired exact location lock}
compare_case protection {set {props(copy[22],DONT_TOUCH)} 0} 1 {Replica unprotected}
compare_case wrong_slr {dict set {positions(copy[22])} slr SLR3} 1 {Replica outside target SLR}
compare_case changed_floorplan {lappend members(user_pb) unexpected_member} 1 {Original floorplan changed}
compare_case child_range {set props(child_hint,GRID_RANGES) wrong_range} 1 {Joint soft region changed}
compare_case changed_connectivity {set {actual_sinks(copy[22]/Q)} other/D} 1 {Local output sink mismatch}
compare_case changed_function {set {configs(copy[22])} {INIT 1'b1}} 1 {Replica function mismatch}
compare_case no_replicas {dict set plan local_broadcast graph replicas {};dict set plan local_broadcast graph new_inputs {};dict set plan local_broadcast graph expected {}} 0
# A second invocation must query current membership, even in the same Tcl
# session and with the same object names. Simulate an intervening ECO boundary.
fixture
set first [run fast [file join $out freshness before] 0]
set members(localrep_SLR0) [lrange $members(localrep_SLR0) 0 end-1]
set {assigned(copy[22])} {}
set second [run fast [file join $out freshness after] 0]
sb::require [expr {[dict get $first code]==0 && [dict get $second code]==1 && [dict get $second result] eq "Replica missing from SLR Pblock"}] "Membership cache leaked across verification"
sb::require [expr {[dict get $second queries localrep_SLR0]==1}] "Next verification did not reread membership"
incr case_count
puts "PASS: $case_count equivalence/rejection/freshness cases; 24 replicas, full membership, nested parent and unchanged report bytes; each SLR membership query 13 -> 1 per verify"
file delete -force $out
