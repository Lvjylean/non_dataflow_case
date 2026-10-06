# Unlock only pipeline-owned combinational buffers; retain FF/CE locality contracts.
namespace eval mobility {}
proc mobility::apply {plan out} {
    set buffers [get_cells -quiet -hier -filter {REF_NAME == LUT1 && NAME =~ f96_identity_*}]
    set reserved [dict get $plan fixed]
    set movable {}; set kept {}; set before {}
    # Batch metadata readback: never issue one placement query per buffer.
    foreach name [sb::names $buffers] init [sb::values INIT $buffers] loc [sb::values LOC $buffers] bel [sb::values BEL $buffers] {
        sb::require [expr {[string tolower $init] eq "2'h2"}] "Owned buffer truth table changed: $name"
        if {[dict exists $reserved $name]} {lappend kept $name; continue}
        lappend movable $name
        lappend before $name [dict create loc $loc bel $bel]
    }
    unset buffers
    rf::property_batches IS_LOC_FIXED false $movable cell
    rf::property_batches IS_BEL_FIXED false $movable cell
    set regions {}
    foreach pb [get_pblocks -quiet f96w_*] {
        set name [get_property NAME $pb]
        lappend regions $name [dict create grid [lsort [get_property GRID_RANGES $pb]] members [lsort [sb::names [get_cells -of_objects $pb]]]]
    }
    dict set plan mobility [dict create schema movable-owned-lut-v1 movable $movable retained_fixed $kept positions_before $before regions $regions]
    if {[llength $movable]} {dict set plan no_op 0}
    verify $plan $out/mobility_after_edit
    return $plan
}
proc mobility::verify {plan out} {
    if {![dict exists $plan mobility]} {return}
    file mkdir $out
    set m [dict get $plan mobility]
    set f [open $out/mobility.tsv w]
    puts $f "cell\tloc\tbel\tloc_fixed\tbel_fixed\tstatus"
    foreach batch [sb::chunks [dict get $m movable] 512] {
        set objects [get_cells $batch]
        sb::require [expr {[lsort [sb::names $objects]] eq [lsort $batch]}] "Movable buffer missing"
        foreach name [sb::names $objects] ref [sb::values REF_NAME $objects] init [sb::values INIT $objects] dt [sb::values DONT_TOUCH $objects] lf [sb::values IS_LOC_FIXED $objects] bf [sb::values IS_BEL_FIXED $objects] loc [sb::values LOC $objects] bel [sb::values BEL $objects] {
            sb::require [expr {$ref eq "LUT1" && [string tolower $init] eq "2'h2" && [sb::one_bit $dt]}] "Movable buffer function/protection changed: $name"
            sb::require [expr {![sb::one_bit $lf] && ![sb::one_bit $bf]}] "Movable buffer reacquired coordinate lock: $name"
            puts $f "$name\t$loc\t$bel\t$lf\t$bf\tPASS"
        }
    }
    close $f
    dict for {name expected} [dict get $m regions] {
        set pb [get_pblocks -quiet [list $name]]
        sb::require [expr {[llength $pb] == 1}] "Missing soft buffer window: $name"
        sb::require [sb::one_bit [get_property IS_SOFT $pb]] "Buffer window became hard: $name"
        sb::require [expr {[lsort [get_property GRID_RANGES $pb]] eq [dict get $expected grid]}] "Buffer window changed: $name"
        sb::require [expr {[lsort [sb::names [get_cells -of_objects $pb]]] eq [dict get $expected members]}] "Buffer membership changed: $name"
    }
    set f [open $out/PASS w]; puts $f "PASS: movable identity buffers, protection and soft-region contracts"; close $f
}
