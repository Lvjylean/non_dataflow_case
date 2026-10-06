# Read-only native equivalence probe. OLD_REGIONAL NEW_REGIONAL DCP OUT ?LIMIT?
# No net inventory, timing, placement, routing, or checkpoint writes.
set out {}
if {[catch {
    if {[llength $argv] ni {4 5}} {error "Expected OLD_REGIONAL NEW_REGIONAL DCP NEW_OUT ?LIMIT?"}
    lassign $argv oldcode newcode input out limit
    if {$limit eq ""} {set limit 512}
    if {![string is integer -strict $limit] || $limit<1 || $limit>2048} {error "Probe limit must be 1..2048"}
    if {[file exists $out]} {error "Refusing existing probe output"}
    file mkdir $out
    foreach f {core.tcl regional.tcl} {uplevel #0 [list source $oldcode/$f]}
    uplevel #0 [list source $newcode/locality_inventory.tcl]
    set input_sha [lindex [exec sha256sum $input] 0]
    set source_hashes {}
    foreach p [list $oldcode/regional.tcl $oldcode/core.tcl $newcode/locality_inventory.tcl] {
        dict set source_hashes [file normalize $p] [lindex [exec sha256sum $p] 0]
    }
    open_checkpoint $input
    set f [open $out/STARTED.tcldict w]
    puts $f [dict create mode readonly_parent_cache_probe input [file normalize $input] input_sha256 $input_sha \
        source_hashes $source_hashes part [get_property PART [current_design]] version [version -short] sample_limit $limit]
    close $f
    # Select real supported leaves from the largest sibling populations. Only
    # bounded representative names are retained per parent; the old helper is
    # still run separately on every selected leaf, not inferred from the parent.
    array set counts {};array set representatives {}
    set inventory_started [clock milliseconds]
    set cells [get_cells -hier -quiet -filter {IS_PRIMITIVE == 1}]
    foreach batch [sb::chunks $cells 1024] {
        foreach name [sb::names $batch] ref [sb::values REF_NAME $batch] {
            if {![locality_inventory::supported $ref]} {continue}
            set parent [file dirname $name]
            if {![info exists counts($parent)]} {set counts($parent) 0;set representatives($parent) {}}
            incr counts($parent)
            if {[llength $representatives($parent)]<64} {lappend representatives($parent) $name}
        }
    }
    unset cells
    set sorted {};foreach parent [array names counts] {lappend sorted [list $counts($parent) $parent]}
    set sorted [lsort -integer -decreasing -index 0 $sorted]
    set selected {};set population {}
    foreach row $sorted {
        lassign $row count parent
        foreach name $representatives($parent) {
            if {[llength $selected]>=$limit} {break}
            lappend selected $name
        }
        lappend population [list $parent $count]
        if {[llength $selected]>=$limit} {break}
    }
    sb::require [expr {[llength $selected]>0}] "No supported native sample"
    set inventory_ms [expr {[clock milliseconds]-$inventory_started}]
    array unset ::rf::ancestor_cache *
    set reference {};set tick [clock microseconds]
    foreach cell $selected {lappend reference [list $cell [rf::protected_ancestor $cell]]}
    set reference_us [expr {[clock microseconds]-$tick}]
    locality_inventory::reset_protection
    set optimized {};set tick [clock microseconds]
    foreach cell $selected {lappend optimized [list $cell [locality_inventory::protected_ancestor $cell]]}
    set optimized_us [expr {[clock microseconds]-$tick}]
    foreach name {reference optimized} {
        set f [open $out/${name}.tcllist w]
        foreach row [set $name] {puts $f $row};close $f
    }
    sb::require [expr {$reference eq $optimized}] "Native per-leaf protected-ancestor mismatch"
    # Rebuild after reset to prove the same scope is not relying on a previous
    # capture's cached result. No live property is changed by this probe.
    locality_inventory::reset_protection
    set repeated {};foreach cell $selected {lappend repeated [list $cell [locality_inventory::protected_ancestor $cell]]}
    sb::require [expr {$reference eq $repeated}] "Reset/rebuild result mismatch"
    sb::require [expr {[lindex [exec sha256sum $input] 0] eq $input_sha}] "Original DCP changed"
    dict for {p expected} $source_hashes {sb::require [expr {[lindex [exec sha256sum $p] 0] eq $expected}] "Probe source changed: $p"}
    set f [open $out/COMPLETE.tcldict w]
    puts $f [dict create status NATIVE_PARENT_EQUIVALENCE_PASS samples [llength $selected] sibling_populations $population \
        reference_us $reference_us optimized_us $optimized_us sample_inventory_ms $inventory_ms \
        unique_native_parent_queries $::locality_inventory::protection_queries \
        native_parent_query_us $::locality_inventory::protection_native_us \
        input_sha256 $input_sha input_unchanged true source_hashes $source_hashes \
        graph_or_property_mutations false checkpoint_written false]
    close $f
    close_design
    exit 0
} message options]} {
    if {[dict exists $options -errorinfo]} {puts stderr [dict get $options -errorinfo]} else {puts stderr $message}
    if {$out ne "" && [file isdirectory $out]} {set f [open $out/FAIL.tcldict w];puts $f [dict create message $message options $options];close $f}
    exit 1
}
