if {[catch {
lassign $argv code input out
file mkdir $out
source $code/code/base/fanout96/core.tcl
source $code/code/base/fanout96/fast.tcl
source $code/code/base/fanout96/quick.tcl
source $code/control/performance_base.tcl
set reference {}
foreach mode {reference boundary} {
    open_checkpoint $input
    f96::spatial_cache
    set ::f96::created 0
    set ::f96::serial 0
    set ::f96::target 16
    set ::boundary::enabled [expr {$mode eq "boundary"}]
    set driver [get_pins root/Q]
    set selected [list [dict create driver $driver driver_name root/Q ref FDRE sinks [f96::loads $driver]]]
    f96::apply $selected $out/$mode
    set f [open $out/$mode/branches.tsv]; set branches [read $f]; close $f
    if {$mode eq "reference"} {set reference $branches} elseif {$branches ne $reference} {error "Tree branch plan changed"}
    write_checkpoint $out/$mode.dcp
    close_design
}
set f [open $out/PASS w]; puts $f "PASS exact production tree branch leaf sets"; close $f
exit
} message options]} {puts stderr [dict get $options -errorinfo]; exit 1}
