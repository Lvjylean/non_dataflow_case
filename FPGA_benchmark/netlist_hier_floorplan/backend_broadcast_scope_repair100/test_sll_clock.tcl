
source [lindex $argv 0]
set mode mixed
proc get_ports {args} {return ap_clk}
proc get_clocks {args} {if {$::mode eq "multiclock"} {return {c1 c2}};return ap_clk}
proc all_registers {args} {return {ram0 dsp0 ff0 ff1}}
proc filter {objects expression} {
    if {$objects ne {ram0 dsp0 ff0 ff1}} {error "Wrong register collection"}
    foreach ref {FDRE FDSE FDCE FDPE} {if {[string first $ref $expression] < 0} {error "Missing primitive filter $ref"}}
    if {$::mode eq "noflop"} {return {}}
    return {ff0 ff1}
}
proc get_pins {args} {
    set i [lsearch -exact $args -of_objects]
    if {[lindex $args [expr {$i+1}]] ne "ff0"} {error "Non-FF chosen for C pin"}
    if {$::mode eq "nopin"} {return {}}
    return ff0/C
}
proc get_nets {args} {if {$::mode eq "ambiguous"} {return {clk0 clk1}};return clk}
set bound [sllph::resolve_clock ap_clk]
if {[dict get $bound ff] ne "ff0" || [dict get $bound net] ne "clk"} {error "Bad mixed primitive resolution"}
foreach mode {multiclock noflop nopin ambiguous} {
    if {![catch {sllph::resolve_clock ap_clk} message]} {error "Did not reject $mode"}
}
puts {PASS: RAM/DSP-first clock collection, FF clock selection, and fail-closed ambiguous/missing bindings}

proc get_property {property object} {return $::protection_value}
foreach {protection_value expected} {{} 0 0 0 false 0 no 0 1 1 true 1 yes 1 TRUE 1} {
    if {[sllph::is_protected ap_clk] != $expected} {error "Wrong unset/boolean DONT_TOUCH handling: $protection_value"}
}
puts {PASS: unset OOC clock protection and explicit Boolean values}
