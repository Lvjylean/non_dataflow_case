# Compare the complete small-fixture graph and physical constraints after ECO.
if {[catch {
lassign $argv code reference fast out
source $code/core.tcl
source $code/regional.tcl
set rows {}
foreach checkpoint [list $reference $fast] {
    open_checkpoint $checkpoint
    rf::reset
    set snapshot {}
    foreach name [lsort [sb::names [get_cells -hier -filter {IS_PRIMITIVE == 1}]]] {
        set object [get_cells [list $name]]
        set ref [get_property REF_NAME $object]
        set configuration {}
        if {$ref in {FDRE FDSE} || [regexp {^LUT[1-6]$} $ref]} {set configuration [sb::config $name]}
        set attributes {}
        foreach key {LOC BEL IS_LOC_FIXED IS_BEL_FIXED DONT_TOUCH} {
            lappend attributes $key [get_property $key $object]
        }
        lappend snapshot [list cell $name $ref $configuration $attributes]
        foreach pin [lsort [sb::names [get_pins -of_objects $object -filter {DIRECTION == IN && IS_LEAF == 1}]]] {
            if {[llength [get_nets -quiet -of_objects [get_pins [list $pin]]]]} {
                lappend snapshot [list input $pin [sb::signal $pin]]
            } else {lappend snapshot [list input $pin disconnected]}
        }
    }
    foreach name [lsort [sb::names [get_pblocks]]] {
        set pb [get_pblocks [list $name]]
        lappend snapshot [list pblock $name [lsort [get_property GRID_RANGES $pb]] \
            [get_property IS_SOFT $pb] [get_property EXCLUDE_PLACEMENT $pb] \
            [lsort [sb::names [get_cells -of_objects $pb]]]]
    }
    lappend rows $snapshot
    close_design
}
if {[lindex $rows 0] ne [lindex $rows 1]} {error "Complete fixture graph/configuration/constraint comparison failed"}
set f [open $out w]
puts $f "PASS: [llength [lindex $rows 0]] complete fixture rows; all leaf inputs, primitive configurations/protection/positions and exact Pblock members/ranges match."
close $f
exit
} message options]} {
puts stderr [dict get $options -errorinfo]
exit 1
}
