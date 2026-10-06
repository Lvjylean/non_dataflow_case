# Run production boundary/edit methods against warning-only native failures.
source [file join [file dirname [info script]] policy.tcl]
set f [open [file join [file dirname [info script]] local_broadcast.tcl]]
set source_text [read $f];close $f
namespace eval lb {}
namespace eval execopt {}
foreach method {unlock_boundaries restore_boundaries require_disconnected apply} {
    set begin [string first "proc lb::$method " $source_text]
    set next [string first "\nproc " $source_text [expr {$begin+1}]]
    if {$begin<0 || $next<0} {error "Missing production method: $method"}
    eval [string range $source_text $begin [expr {$next-1}]]
}
proc lb::log {s} {}
proc lb::pblock_snapshot {} {return {}}
proc lb::source_net {local key} {return [dict get $::source_nets $key]}
proc sb::names {objects} {return $objects}
proc sb::pin {pin} {return $pin}
proc sb::values {property objects} {
    set out {}
    foreach name $objects {
        if {$property eq "TYPE"} {lappend out [dict get $::types $name]} else {lappend out [dict get $::flags $name]}
    }
    return $out
}
proc sb::spatial_cache {} {}
proc sb::reset_edit_state {} {}
proc sb::save {plan path} {}
proc sb::net_at {pin} {return [dict get $::connected $pin]}
proc sb::loads {pin} {return [dict get $::before_loads $pin]}
proc execopt::exact_objects {kind names} {
    foreach name $names {
        if {$kind eq "pin"} {sb::require [dict exists $::connected $name] "Missing pin $name"} else {sb::require [dict exists $::flags $name] "Missing $kind $name"}
    }
    return $names
}
proc get_nets {args} {
    set of [lsearch -exact $args -of_objects]
    if {$of>=0} {
        set out {}
        foreach pin [lindex $args [expr {$of+1}]] {
            if {[dict exists $::connected $pin]} {lappend out {*}[dict get $::connected $pin]}
        }
    } else {set out [lindex $args end]}
    if {[lsearch -exact $args -segments]>=0} {
        set expanded {}
        foreach net $out {lappend expanded {*}[dict get $::segments $net]}
        set out $expanded
    }
    return [lsort -unique $out]
}
proc get_clocks {args} {
    set out {}
    foreach name [lindex $args end] {if {$name in {clock_net clock_global_alias}} {lappend out clk}}
    return $out
}
proc get_property {property objects} {
    if {$property eq "NAME"} {return $objects}
    return [sb::values $property $objects]
}
proc set_property {property value objects} {
    foreach name $objects {
        if {$value eq "false" && $name eq $::ignore_unlock} {continue}
        dict set ::flags $name $value
    }
}
proc reset_property {property objects} {foreach name $objects {dict set ::flags $name ""}}
proc route_design {args} {
    foreach net [lindex $args end] {sb::require [expr {$net ni {clock_net constant_net clock_global_alias constant_global_alias}}] "Unrouted clock/supply"}
}
proc execopt::disconnect_segment {net pins} {
    foreach pin $pins {if {!$::ignore_disconnect} {dict set ::connected $pin {}}}
}
proc execopt::connect_many {pairs} {
    incr ::connect_calls
    if {$::fail_connect} {error mock_native_connect_failure}
    foreach {net pin} $pairs {dict set ::connected $pin $net}
}
proc fixture {} {
    set ::flags {}
    foreach {name value} {
        top true top/root true top/old true top/input false top/alias true
        top/newinput {} top/sink true top/reused {} top/unrelated true
        root_net true old_driver_net true old_sink_net true input_net false
        alias_net true newinput_net true clock_net true constant_net true unrelated_net true
        clock_global_alias true constant_global_alias true
    } {dict set ::flags $name $value}
    set ::types {};set ::segments {}
    foreach name {root_net old_driver_net old_sink_net input_net alias_net newinput_net clock_net constant_net unrelated_net clock_global_alias constant_global_alias} {
        dict set ::types $name SIGNAL;dict set ::segments $name [list $name]
    }
    dict set ::types constant_net GROUND
    dict set ::types constant_global_alias GROUND
    dict set ::segments clock_net {clock_net clock_global_alias}
    dict set ::segments constant_net {constant_net constant_global_alias}
    # Include a sink-only native segment, separate from source resolution.
    dict set ::segments old_sink_net {old_driver_net old_sink_net}
    set ::source_nets [dict create top/root/Q root_net top/old/O old_driver_net top/input/Q input_net top/alias/O alias_net top/newinput/O newinput_net \
        {clock clk} clock_net {constant 0} constant_net]
    set ::connected [dict create top/sink/D old_sink_net top/reused/I0 old_sink_net clk clock_net rst constant_net]
    set ::before_loads [dict create top/old/O {top/reused/I0 top/sink/D} top/alias/O {}]
    set ::ignore_unlock {};set ::ignore_disconnect 0;set ::fail_connect 0;set ::connect_calls 0
    set nets {}
    foreach key {top/root/Q top/old/O top/input/Q top/alias/O top/newinput/O} {
        dict set nets $key [dict create kind ordinary signal [list drivers [list $key]] anchor $key before {}]
    }
    dict set nets {clock clk} [dict create kind clock signal {clock clk} anchor clk before {}]
    dict set nets {constant 0} [dict create kind constant signal {constant 0} anchor rst before {}]
    set inputs [dict create D [dict create key top/input/Q] CE [dict create key top/alias/O] C [dict create key {clock clk}] R [dict create key {constant 0}]]
    set roots [dict create top/root/Q [dict create inputs $inputs]]
    set graph [dict create replicas [dict create copy [dict create key top/root/Q]] \
        moves [dict create top/sink/D {top/old/O copy/Q} top/reused/I0 {top/old/O top/alias/O}] \
        new_inputs [dict create copy/D top/newinput/O copy/C {clock clk} copy/R {constant 0}]]
    return [dict create snapshot [dict create roots $roots nets $nets] graph $graph copies {}]
}
proc assert_restored {original} {
    dict for {name value} $original {
        sb::require [expr {[dict get $::flags $name] eq $value}] "Original protection not restored: $name"
    }
}
set local [fixture];set original $::flags
set boundary [lb::unlock_boundaries $local]
foreach name {old_driver_net old_sink_net newinput_net alias_net top/old top/sink top/reused top/newinput top} {
    sb::require [expr {![sb::one_bit [dict get $::flags $name]]}] "Missed edit boundary $name"
}
sb::require [expr {[dict get $::flags unrelated_net] eq "true" && [dict get $::flags top/unrelated] eq "true"}] "Unlocked unrelated objects"
foreach net {clock_net constant_net clock_global_alias constant_global_alias} {sb::require [expr {$net ni [dict get $boundary unroute]}] "Clock/supply in unroute: $net"}
foreach net {clock_global_alias constant_global_alias} {
    sb::require [expr {[dict get $::flags $net] eq "true" && ![dict exists $boundary properties net $net]}] "Unlocked global clock/supply alias: $net"
}
lb::restore_boundaries [dict get $boundary properties];assert_restored $original

set local [fixture];set original $::flags;set ::ignore_unlock old_sink_net
set code [catch {lb::unlock_boundaries $local} why]
sb::require [expr {$code && [string match {*remains DONT_TOUCH*old_sink_net*} $why]}] "Ignored unlock was not rejected: $why"
assert_restored $original

# A falsely ordinary snapshot clock must still be excluded from native unroute.
set local [fixture]
dict set local snapshot nets {clock clk} kind ordinary
set boundary [lb::unlock_boundaries $local]
foreach net {clock_net clock_global_alias} {sb::require [expr {$net ni [dict get $boundary unroute]}] "Native clock guard ignored"}
lb::restore_boundaries [dict get $boundary properties]

# Exercise the actual apply catch/restore path; no replicas are needed to prove
# that warning-only disconnect failure cannot reach connect_many.
foreach failure {disconnect connect success} {
    set local [fixture];set original $::flags
    dict set local snapshot roots {}
    set nets {}
    foreach key {top/old/O top/alias/O} {
        set record [dict get $local snapshot nets $key]
        dict set record before [dict get $::before_loads $key]
        dict set nets $key $record
    }
    dict set local snapshot nets $nets
    dict set local graph [dict create replicas {} new_inputs {} moves [dict create top/sink/D {top/old/O top/alias/O}]]
    set ::ignore_disconnect [expr {$failure eq "disconnect"}]
    set ::fail_connect [expr {$failure eq "connect"}]
    set folder [file join /tmp lb_protection_[pid]];file mkdir $folder
    set code [catch {lb::apply [dict create local_broadcast $local] $folder} why]
    file delete -force $folder
    assert_restored $original
    if {$failure eq "disconnect"} {
        sb::require [expr {$code && [string match {*Disconnect did not release edit pin:*top/sink/D*old_sink_net*} $why] && !$::connect_calls}] "Silent disconnect reached connect: $why"
    } elseif {$failure eq "connect"} {
        sb::require [expr {$code && $why eq "mock_native_connect_failure" && $::connect_calls==1}] "Native connect failure not retained: $why"
    } else {
        sb::require [expr {!$code && $::connect_calls==1 && [dict get $::connected top/sink/D] eq "alias_net"}] "Successful edit failed: $why"
    }
}
puts "PASS: actual move/new-input boundaries, hierarchy segments, bounded protection, clock/supply guard, readback, disconnected pins and error restoration"
