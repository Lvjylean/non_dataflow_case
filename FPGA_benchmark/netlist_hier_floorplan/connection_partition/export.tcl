# Read-only bulk export for connectivity-only coarse partitioning.
set_param general.maxThreads 4
proc phase {s} {puts "COARSE_PHASE [clock seconds] $s"; flush stdout}
proc row {f args} {puts $f [join $args \t]}
if {$argc != 2} {error "Expected checkpoint and new output directory"}
set dcp [file normalize [lindex $argv 0]]
set out [file normalize [lindex $argv 1]]
if {[file exists $out]} {error "Refusing to overwrite export"}
file mkdir $out
phase open
open_checkpoint $dcp
phase inventory
set cells [get_cells -hier -filter {IS_PRIMITIVE == 1}]
array set primitive {}
foreach n [get_property NAME $cells] r [get_property REF_NAME $cells] {
    set primitive($n) $r
}
set f [open $out/cells.tsv w]
row $f cell_id cell_name primitive original_hierarchy
set count 0
foreach n [lsort [array names primitive]] {
    set ancestor $n
    set nested 0
    while {[set slash [string last / $ancestor]] >= 0} {
        set ancestor [string range $ancestor 0 [expr {$slash-1}]]
        if {[info exists primitive($ancestor)]} {set nested 1; break}
    }
    if {$nested} {continue}
    set slash [string last / $n]
    set hierarchy [expr {$slash < 0 ? "TOP" : [string range $n 0 [expr {$slash-1}]]}]
    row $f c$count $n $primitive($n) $hierarchy
    incr count
}
close $f
phase "inventory_done cells=$count"
# Native bulk EDIF preserves hierarchy aliases and avoids per-net Tcl queries.
write_edif $out/netlist.edf
set f [open $out/input.tsv w]
row $f checkpoint $dcp
row $f part [get_property PART [current_design]]
row $f vivado [version -short]
row $f cells $count
close $f
set f [open $out/complete.txt w]; puts $f COMPLETE; close $f
phase complete
close_design
exit
