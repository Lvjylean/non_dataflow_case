cd $::env(RUN_DIR)
set_param general.maxThreads 4
open_checkpoint $::env(INPUT_DCP)
set f [open ../path_net_fanout.tsv r]; set lines [split [read $f] \n]; close $f
set out [open intra_site_audit.tsv w]
puts $out "net\tphysical_site_pins\troute_status\tcell_sites\tclassification"
set count 0; set unknown 0
foreach line [lrange $lines 1 end] {
    set row [split $line \t]
    if {[llength $row] < 6 || [lindex $row 4] ne "UNKNOWN"} {continue}
    set name [lindex $row 0]
    set net [get_nets -quiet $name]
    if {[llength $net] != 1} {error "Missing audit net $name"}
    set status [get_property ROUTE_STATUS $net]
    set pins [get_pins -quiet -leaf -of_objects $net]
    set cells [get_cells -quiet -of_objects $pins]
    set sites [lsort -unique [get_property LOC $cells]]
    set loads [get_pins -quiet -leaf -of_objects $net -filter {DIRECTION == IN}]
    set sitepins [lsort -unique [get_site_pins -quiet -of_objects $loads]]
    set physical [llength $sitepins]; set class RESOLVED
    if {$physical == 0} {
        if {$status eq "INTRASITE" && [llength $sites] == 1 && $sites ne ""} {
            set class INTRASITE_CONFIRMED
        } else {set physical UNKNOWN; set class UNRESOLVED; incr unknown}
    }
    puts $out "$name\t$physical\t$status\t[join $sites ,]\t$class"
    incr count
}
close $out
set f [open audit_complete.txt w]; puts $f "count=$count unresolved=$unknown"; close $f
