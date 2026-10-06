source [file join [file dirname [info script]] core.tcl]
source [file join [file dirname [info script]] regional.tcl]
proc assert {value message} {if {![uplevel 1 [list expr $value]]} {error $message}}
rename rf::position rf::real_position
proc rf::position {name} {return $::locations($name)}
proc get_cells {args} {
    set result {}; foreach name [lindex $args end] {if {[info exists ::flags($name)]} {lappend result $name}}; return $result
}
proc get_nets {args} {return [get_cells {*}$args]}
proc get_property {prop objects} {
    set values {}
    foreach name $objects {
        switch $prop {
            NAME {lappend values $name}
            DONT_TOUCH {lappend values $::flags($name)}
            REF_NAME {lappend values $::refs($name)}
            IS_LOC_FIXED - IS_BEL_FIXED {lappend values 1}
            default {error "Unexpected property $prop"}
        }
    }
    if {[llength $objects] == 1} {return [lindex $values 0]}
    return $values
}
proc reset_property {property objects} {foreach name $objects {set ::flags($name) ""; incr ::writes}}
proc fixture {} {
    array unset ::flags *; array unset ::refs *; array unset ::locations *
    array set ::flags {native_lut 1 protected 1 net_a 0}
    array set ::refs {native_lut LUT1 protected FDRE}
    set ::locations(native_lut) {loc SLICE_X1Y1 bel SLICEL.A6LUT cr X0Y0 slr SLR0}
    set ::writes 0
    return [dict create fixed [list native_lut $::locations(native_lut)] protection \
        [dict create cells {native_lut {} protected 1} nets {net_a 0}]]
}
set out [file join [pwd] native_lut_protection_test_[pid]]
set plan [fixture]
assert {[rf::restore_native_lut_protection $plan $out] == 1} "Expected one observed promotion"
assert {$flags(native_lut) eq "" && $flags(protected) eq "1" && $flags(net_a) eq "0" && $writes == 1} "Original values changed"
assert {[rf::restore_native_lut_protection $plan $out] == 0 && $writes == 1} "Repeated call was not a no-op"
foreach scenario {lost_protection different_primitive wrong_position missing_object net_promotion originally_false not_fixed} {
    set plan [fixture]
    switch $scenario {
        lost_protection {set flags(protected) 0}
        different_primitive {set refs(native_lut) LUT2}
        wrong_position {set locations(native_lut) {loc SLICE_X2Y1 bel SLICEL.A6LUT cr X0Y0 slr SLR0}}
        missing_object {unset flags(protected)}
        net_promotion {set flags(net_a) 1}
        originally_false {dict set plan protection cells native_lut 0}
        not_fixed {dict set plan fixed {}}
    }
    assert {[catch {rf::restore_native_lut_protection $plan $out} message]} "Unsupported drift accepted: $scenario"
    assert {$writes == 0 && $flags(native_lut) eq "1"} "Partial restoration occurred on rejection: $scenario"
}
set plan [fixture]
rename reset_property normal_reset_property
proc reset_property {property objects} {incr ::writes}
assert {[catch {rf::restore_native_lut_protection $plan $out} message options]} "Sticky native property accepted"
assert {[dict get $options -errorcode] eq {RF NATIVE_LUT_PROTECTION_STICKY}} "Missing typed recovery signal"
assert {$flags(native_lut) eq "1"} "Sticky state unexpectedly changed"
set flags(protected) 0
assert {[catch {rf::restore_native_lut_protection $plan $out} message options]} "Unknown drift accepted"
assert {[dict get $options -errorcode] ne {RF NATIVE_LUT_PROTECTION_STICKY}} "Unknown drift became recoverable"
file delete -force $out
puts "PASS: exact restoration, atomic rejection and typed sticky-property recovery; unknown drift stays fatal"
