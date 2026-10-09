# Read-only performance/equivalence proof on a real serialized candidate view.
# CODE SNAPSHOT OUTPUT. No checkpoint, design edits, placement, or routing.
if {[catch {
lassign $argv code snapshot output
if {[file exists $output]} {error "Refusing to overwrite array probe evidence"}
file mkdir $output
namespace eval locality_inventory {}
source $code/code/regional/locality_input_snapshot.tcl
set tick [clock microseconds];source $snapshot
set load_us [expr {[clock microseconds]-$tick}]
set tick [clock microseconds]
locality_inventory::connection_install $locality_reuse_snapshot
set install_us [expr {[clock microseconds]-$tick}]
set cells [dict get $locality_reuse_snapshot cells]
set nets [dict get $locality_reuse_snapshot nets]
dict for {name item} $cells {
    if {![info exists ::locality_inventory::connection_cells($name)] || $item ne $::locality_inventory::connection_cells($name)} {error "Cell mismatch: $name"}
}
dict for {name item} $nets {
    dict set item before [lsort -unique [dict get $item before]]
    if {![info exists ::locality_inventory::connection_nets($name)] || $item ne $::locality_inventory::connection_nets($name)} {error "Net mismatch: $name"}
}
set names [dict keys $cells];set count [llength $names]
if {!$count} {error "No real candidate cache cells"}
set f [open $output/performance.tsv w]
puts $f "operation\tsample\telapsed_us"
puts $f "source\t0\t$load_us";puts $f "install\t0\t$install_us"
foreach index [list 0 [expr {$count/2}] [expr {$count-1}]] {
    set name [lindex $names $index];set pin [lindex [dict keys [dict get $cells $name]] 0]
    for {set repeat 0} {$repeat<3} {incr repeat} {
        set tick [clock microseconds]
        set before [dict get $locality_reuse_snapshot cells $name $pin]
        puts $f "old_nested_get\t$index:$repeat\t[expr {[clock microseconds]-$tick}]"
        set tick [clock microseconds]
        set after [dict get $::locality_inventory::connection_cells($name) $pin]
        puts $f "new_array_get\t$index:$repeat\t[expr {[clock microseconds]-$tick}]"
        if {$after ne $before} {error "Lookup value changed"}
        set tick [clock microseconds]
        set before [dict exists $locality_reuse_snapshot cells __missing_candidate__]
        puts $f "old_missing\t$index:$repeat\t[expr {[clock microseconds]-$tick}]"
        set tick [clock microseconds]
        set after [info exists ::locality_inventory::connection_cells(__missing_candidate__)]
        puts $f "new_missing\t$index:$repeat\t[expr {[clock microseconds]-$tick}]"
        if {$before ne $after} {error "Missing-key semantics changed"}
    }
}
close $f
set f [open $output/PASS w]
puts $f [list status PASS cells [array size ::locality_inventory::connection_cells] nets [array size ::locality_inventory::connection_nets] bytes [file size $snapshot] version [version -short]]
close $f
puts "INPUT_ARRAY_COMPLETE $output"
} message options]} {puts stderr [dict get $options -errorinfo];exit 1}
exit 0
