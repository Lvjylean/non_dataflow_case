source [file join [file dirname [info script]] core.tcl]
proc get_timing_paths {args} {error "Structural selection must not query timing"}
set ::test_roots {clock_net ff_net ce_net ram_net local_ce data_lut}
set ::test_drivers [dict create ff_net ff0/Q ce_net lut0/O ram_net ram0/DOUTADOUT local_ce lut1/O data_lut lut2/O]
set ::test_loads [dict create data_lut {data0/D data1/D}]
set ::test_refs [dict create ff0 FDRE lut0 LUT2 lut1 LUT1 ram0 RAMB36E2 lut2 LUT4]
set ::test_slrs [dict create ff0 SLR0 lut0 SLR0 lut1 SLR0]
for {set i 0} {$i<16} {incr i} {
    dict lappend ::test_loads ff_net helper${i}/I0
    dict lappend ::test_loads ce_net remote${i}/CE
    dict lappend ::test_loads local_ce local${i}/CE
    dict set ::test_refs remote$i FDRE; dict set ::test_refs local$i FDSE
    dict set ::test_slrs remote$i SLR1; dict set ::test_slrs local$i SLR0
}
proc get_clock_regions {} {return {CR0 CR1}}
proc get_pblocks {args} {return {}}
proc get_slrs {args} {return SLR[string index [lindex $args end] end]}
proc get_sites {args} {return SITE[string index [lindex $args end] end]}
proc get_cells {args} {
    if {[lindex $args 0] eq "-quiet"} {return {}}
    return {ff0}
}
proc get_property {property objects} {
    if {$property eq "NAME"} {return $objects}
    if {$property eq "REF_NAME"} {return FDRE}
    error "Unexpected property query: $property"
}
proc get_nets {args} {
    if {[lsearch -exact $args -hier]>=0 || [lsearch -exact $args -top_net_of_hierarchical_group]>=0} {return $::test_roots}
    return [lindex $args end]
}
proc get_clocks {args} {if {[lindex $args end] eq "clock_net"} {return clk};return {}}
proc get_pins {args} {
    set filter [lsearch -exact $args -filter]
    if {$filter<0} {return [lindex $args end]}
    if {[string match {*REF_PIN_NAME == Q*} [lindex $args [expr {$filter+1}]]]} {return $::test_roots}
    set n [lindex $args [expr {[lsearch -exact $args -of_objects]+1}]]
    if {$n eq "clock_net"} {error "Clock loads must not be expanded"}
    if {[string match {*DIRECTION == OUT*} [lindex $args [expr {$filter+1}]]]} {return [dict get $::test_drivers $n]}
    if {$n eq "ram_net"} {error "RAM data loads must not be expanded"}
    if {$n eq "data_lut" && ![string match {*REF_PIN_NAME == CE*} [lindex $args [expr {$filter+1}]]]} {error "Data-only LUT must not expand all loads"}
    set result [dict get $::test_loads $n]
    if {[string match {*REF_PIN_NAME == CE*} [lindex $args [expr {$filter+1}]]]} {return [lsearch -all -inline -glob $result */CE]}
    return $result
}
rename sb::prefetch sb::native_prefetch
proc sb::prefetch {args} {}
rename sb::ref sb::native_ref
proc sb::ref {name} {return [dict get $::test_refs $name]}
rename sb::position sb::native_position
proc sb::position {name} {return [dict create slr [dict get $::test_slrs $name]]}
set out [file join /tmp sbeco_structural_test_[pid]]
file mkdir $out
set seeds [sb::structural_seeds $out 16]
sb::require [expr {[dict get $seeds data_candidates] eq {ff0}}] "Full-net FF candidate"
sb::require [expr {[dict size [dict get $seeds ce_targets]] == 16}] "Cross-SLR CE type selection"
dict for {name slr} [dict get $seeds ce_targets] {sb::require [expr {$slr eq "SLR1"}] "Local CE must not be selected"}
set ::test_roots {}
set sb::selection structure
set plan [sb::scan $out 1000 16]
sb::require [expr {[dict get $plan no_op] && [dict get $plan sampled_paths] == 0}] "Empty structural plan is a valid no-op"
file delete -force $out
puts "PASS: structural FF/CE selection, clock/RAM exclusions, no timing queries, valid no-op"
