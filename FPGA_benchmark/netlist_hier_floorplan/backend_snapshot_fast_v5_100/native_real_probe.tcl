# Compare a bounded real-design sample without touching its input checkpoint.
if {[catch {
lassign $argv code input out reference_dir
file mkdir $out
source $code/code/base/fanout96/core.tcl
source $code/code/base/fanout96/fast.tcl
source $code/code/base/fanout96/quick.tcl
source $code/code/base/fanout96/hybrid.tcl
source $code/control/performance_base.tcl
set requested {}; set reference {}; set modes {reference boundary}
if {$reference_dir ne ""} {
    set f [open $reference_dir/requested.txt]; set requested [string trim [read $f]]; close $f
    set f [open $reference_dir/reference/branches.tsv]; set reference [read $f]; close $f
    set modes {boundary}
}
foreach mode $modes {
    open_checkpoint $input
    route_design -unroute
    f96::spatial_cache
    set ::f96::created 0; set ::f96::serial 0
    set ::boundary::enabled [expr {$mode eq "boundary"}]
    if {$mode eq "reference"} {
        set all [f96::scan $out/discovery 0]
        lassign [f96::split_actions $all $out/actions] editable native unsupported
        set choices {}
        foreach item $editable {
            set driver [dict get $item driver_name]
            set segments [llength [get_nets -segments -of_objects [get_pins [list $driver]]]]
            lappend choices [list $segments $driver]
        }
        foreach row [lrange [lsort -integer -decreasing -index 0 $choices] 0 3] {lappend requested [lindex $row 1]}
        set f [open $out/requested.txt w]; puts $f $requested; close $f
    }
    set selected {}
    foreach name $requested {
        set driver [get_pins [list $name]]
        lappend selected [dict create driver $driver driver_name $name ref [get_property REF_NAME [get_cells -of_objects $driver]] sinks [f96::loads $driver]]
    }
    f96::apply $selected $out/$mode
    set f [open $out/$mode/branches.tsv]; set branches [read $f]; close $f
    if {$mode eq "reference"} {set reference $branches} elseif {$branches ne $reference} {error "Real-design grouping or leaf sets changed"}
    # The production transformation has read back each root, helper and leaf set.
    close_design
}
set f [open $out/PASS w]; puts $f "PASS actual TRTRS sample, exact branch/root leaf sets and unchanged grouping"; close $f
exit
} message options]} {puts stderr [dict get $options -errorinfo]; exit 1}
