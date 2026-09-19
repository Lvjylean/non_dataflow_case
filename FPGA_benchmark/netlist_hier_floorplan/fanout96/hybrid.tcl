# Protected floating-point IP must be optimized by Vivado itself. Never clear
# encryption rights or attempt to modify protected internal netlist objects.
proc f96::protected_ip_pin {pin} {
    # Conservative provenance selector for this HLS/Vivado floating-point family.
    # These i_synth internals rejected direct ECO edits with Coretcl 2-76.
    return [string match */inst/i_synth/* $pin]
}
proc f96::split_actions {selected directory} {
    variable target
    file mkdir $directory
    set editable {}; set native {}; set unsupported {}
    set f [open $directory/actions.tsv w]
    puts $f "driver\tref\tlogical\tprotected_driver\tprotected_loads\taction\tconstraint_status"
    foreach item $selected {
        set d [dict get $item driver]; set ref [dict get $item ref]
        set pd [protected_ip_pin $d]; set pl 0
        foreach p [dict get $item sinks] {if {[protected_ip_pin $p]} {incr pl}}
        set action IDENTITY_TREE; set status NA
        if {$pd || $pl} {
            if {[regexp {^(FD(RE|SE|CE|PE)|LUT[1-6](_2)?)$} $ref]} {
                set action NATIVE_REPLICATION
                set root [get_nets -of_objects $d]
                set rc [catch {set_property FORCE_MAX_FANOUT $target $root} detail]
                set status [expr {$rc ? "PROPERTY_REJECTED" : "PROPERTY_SET"}]
                if {$rc} {set action PROTECTED_UNSUPPORTED; lappend unsupported $item} else {lappend native $item}
            } else {set action PROTECTED_UNSUPPORTED; lappend unsupported $item}
        } else {lappend editable $item}
        puts $f "$d\t$ref\t[llength [dict get $item sinks]]\t$pd\t$pl\t$action\t$status"
    }
    close $f
    return [list $editable $native $unsupported]
}
proc f96::force_native {selected directory} {
    file mkdir $directory
    set ns {}
    set rf [open $directory/resolved_targets.tsv w]
    puts $rf "requested_driver\tresolved_driver\tresolved_net\tstatus"
    foreach item $selected {
        set pin [dict get $item driver_name]
        set current [get_pins -quiet [list $pin]]
        if {![llength $current]} {
            puts $rf "$pin\t\t\tNO_LONGER_PRESENT"
            continue
        }
        if {[llength $current] != 1 || [get_property NAME $current] ne $pin} {error "Native target name resolved ambiguously: $pin"}
        set current_nets [get_nets -quiet -of_objects $current]
        foreach n $current_nets {
            puts $rf "$pin\t[get_property NAME $current]\t[get_property NAME $n]\tRESOLVED"
            lappend ns [get_property NAME $n]
        }
    }
    close $rf
    if {![llength $ns]} {return}
    set rc [catch {phys_opt_design -force_replication_on_nets [get_nets $ns]} detail]
    set f [open $directory/native_command.tsv w]
    puts $f "target_nets\treturn_code\tdetail"
    puts $f "[llength $ns]\t$rc\t[string map [list \n { }] $detail]"; close $f
}
