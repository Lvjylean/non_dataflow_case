# Optional bounded multi-object creation; source after fast.tcl.
# Vivado UG835 2023.2 create_cell/create_net accept a list of instance names.
proc f96::fast_create {names net_names} {
    for {set i 0} {$i < [llength $names]} {incr i 128} {
        create_cell -reference LUT1 [lrange $names $i [expr {$i+127}]]
        create_net [lrange $net_names $i [expr {$i+127}]]
    }
    if {[llength [get_cells $names]] != [llength $names] ||
        [llength [get_nets $net_names]] != [llength $net_names]} {
        error "Batched helper creation incomplete"
    }
}

proc f96::residual_signature {selected} {
    set rows {}
    foreach item $selected {
        lappend rows [list [dict get $item driver_name] [dict get $item ref] \
            [lsort [plain_names [dict get $item sinks]]]]
    }
    return [lsort $rows]
}

