# Exact read-only inventory equivalence. OLD_CODE NEW_CODE DCP NEW_OUT.
if {[catch {
lassign $argv old new checkpoint out
if {[file exists $out]} {error "Refusing to overwrite native inventory evidence"}
file mkdir $out
source $old/code/regional/core.tcl
source $old/code/regional/regional.tcl
source $old/code/regional/locality_inventory.tcl
rename locality_inventory::capture locality_inventory::capture_original
source $new/code/regional/locality_inventory.tcl
open_checkpoint $checkpoint
set tick [clock microseconds]
set original [locality_inventory::capture_original $out/reference]
set reference_us [expr {[clock microseconds]-$tick}]
set tick [clock microseconds]
set optimized [locality_inventory::capture $out/batch batch]
set batch_us [expr {[clock microseconds]-$tick}]
sb::require [expr {[dict get $optimized acquisition_profile] eq "batch"}] "Batch profile unexpectedly fell back"
foreach name {cells edges diagnostics} {
    set f [open $out/reference/$name.tsv];set a [read $f];close $f
    set f [open $out/batch/$name.tsv];set b [read $f];close $f
    sb::require [expr {[lsort [split [string trimright $a \n] \n]] eq [lsort [split [string trimright $b \n] \n]]}] "Native complete inventory mismatch: $name"
}
foreach key {schema status cells editable_cells nets edges constant_edges clock_nets fixed_nets disconnected_inputs diagnostics semantics} {
    sb::require [expr {[dict get $original $key] eq [dict get $optimized $key]}] "Native inventory metadata mismatch: $key"
}
set f [open $out/COMPLETE.tcldict w]
puts $f [dict create status PASS checkpoint $checkpoint input_sha256 [lindex [exec sha256sum $checkpoint] 0] \
    version [version -short] part [get_property PART [current_design]] \
    cells [dict get $optimized cells] nets [dict get $optimized nets] edges [dict get $optimized edges] \
    reference_us $reference_us batch_us $batch_us graph_properties_mutated false]
close $f
close_design
exit 0
} message options]} {puts stderr [dict get $options -errorinfo];exit 1}
