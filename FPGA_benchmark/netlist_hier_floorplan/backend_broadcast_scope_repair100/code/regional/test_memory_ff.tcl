# Exercise the complete structural plan for RAM-fed and FF-fed broadcasts.
source [file join [file dirname [info script]] core.tcl]
proc get_timing_paths {args} {error "Structural planning must not use timing selection"}
proc get_cells {args} {return {}}
proc get_pblocks {args} {return {}}
set ::refs [dict create ramfed FDRE fffed FDRE statusfed FDRE mem RAMB36E2 upstream FDRE ce LUT2]
proc get_property {property object} {
    if {$property eq "REF_NAME"} {
        if {[dict exists $::refs $object]} {return [dict get $::refs $object]}
        if {[string match *helper* $object]} {return LUT1}
        return URAM288
    }
    if {$property eq "INIT"} {return "2'h2"}
    error "Unexpected query $property $object"
}
foreach name {cell ref counts structural_seeds signal loads position prefetch config inputs canonical drivers} {
    rename sb::$name sb::native_$name
}
proc sb::cell {name} {return $name}
proc sb::ref {name} {return [get_property REF_NAME $name]}
proc sb::counts {} {return [dict create ff 3 lut 33]}
proc sb::structural_seeds {out limit} {return [dict create data_candidates {ramfed fffed statusfed} ce_targets {} net_roots 3]}
proc sb::signal {pin} {
    switch -exact $pin {
        ramfed/D {return [list drivers [list {mem/DOUTADOUT[25]}]]}
        fffed/D {return [list drivers {upstream/Q}]}
        statusfed/D {return [list drivers {mem/SBITERR}]}
    }
    switch [file tail $pin] {
        R {return {constant GROUND}}
        CE {return {drivers ce/O}}
        C {return {clock clk}}
        default {error "Unexpected signal $pin"}
    }
}
proc sb::loads {pin} {
    if {[file tail $pin] eq "Q"} {
        set result {}; set c [file dirname $pin]
        for {set i 0} {$i<16} {incr i} {lappend result ${c}_helper${i}/I0}
        return $result
    }
    if {[regexp {^(.+)_helper([0-9]+)/O$} $pin unused c i]} {return [list ${c}_uram${i}/DIN_B\[25\]]}
    error "Unexpected loads $pin"
}
proc sb::position {name} {
    set slr SLR1
    if {[regexp {(helper|uram)([0-9]+)$} $name unused kind i] && $i>=8} {set slr SLR2}
    return [dict create slr $slr loc site_$name bel LUT]
}
proc sb::prefetch {names} {}
proc sb::config {name} {
    if {[get_property REF_NAME $name] eq "FDRE"} {return [dict create INIT 1'b0 IS_C_INVERTED 0 IS_D_INVERTED 0 IS_R_INVERTED 0]}
    return [dict create INIT 2'h2]
}
proc sb::inputs {name} {
    if {$name eq "ce"} {return [dict create I0 [dict create net up signal {drivers upstream/Q}] I1 [dict create net zero signal {constant GROUND}]]}
    set result {}
    foreach p {D C CE R} {dict set result $p [dict create net net_$p signal [signal $name/$p]]}
    return $result
}
proc sb::canonical {pin} {return ce_net}
proc sb::drivers {pin} {return ce/O}
set sb::selection structure
set out [file join /tmp sbeco_memory_test_[pid]]
file mkdir $out
set plan [sb::scan $out 1000 16]
sb::require [expr {[dict get $plan ff_added] == 2}] "Both existing FFs must have a remote copy"
sb::require [expr {[dict get $plan data ramfed d_source_kind] eq "bram_data"}] "RAM-fed FF must be selected"
sb::require [expr {[dict get $plan data fffed d_source_kind] eq "ff"}] "Existing FF-fed support retained"
sb::require [expr {![dict exists $plan data statusfed]}] "Memory status output is not data"
sb::require [expr {[dict get $plan data ramfed inputs D signal] eq [list drivers [list {mem/DOUTADOUT[25]}]]}] "Clone must sample the same BRAM output"
dict for {c item} [dict get $plan data] {
    sb::require [expr {[dict keys [dict get $item replicas]] eq {SLR2}}] "One peer FF on the remote die"
    sb::require [expr {[llength [dict get $item groups SLR1]] == 8 && [llength [dict get $item groups SLR2]] == 8}] "Preserve local groups"
    sb::require [expr {[dict size [dict get $item helpers]] == 16}] "Preserve every helper and its data leaves"
}
sb::require [expr {[dict get $plan lut_added] == 1}] "New memory-fed FF must participate in CE localization"
set ce_item [lindex [dict values [dict get $plan ce]] 0]
sb::require [expr {[llength [dict get $ce_item loads]] == 2 && [dict get $ce_item target_slr] eq "SLR2"}] "Parallel local CE covers both replicas"
file delete -force $out
puts "PASS: full RAM-fed/FF-fed structural plans, unchanged D and helper groups, local CE, rejected memory status"
