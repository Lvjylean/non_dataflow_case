# Use the real loader/backend/helper files; stop at the first native query.
set code [file dirname [file normalize [info script]]]
set ::env(BL_LOCALITY) 1
proc write_checkpoint {args} {error UNEXPECTED_CHECKPOINT_WRITE}
source $code/checkpoint_io.tcl
source $code/physical_eco.tcl
source $code/code/regional/core.tcl
source $code/code/regional/regional.tcl
source $code/code/regional/local_broadcast.tcl
lb::install
if {[llength [info commands ::bl::discover]]} {error "Fixture must begin before lazy backend loading"}
proc get_cells {args} {error NATIVE_BOUNDARY_REACHED}
set rc [catch {lb::discover unused 16} why]
if {!$rc || $why ne "NATIVE_BOUNDARY_REACHED"} {error "Actual lazy discovery did not reach native boundary: $why"}
foreach command {::bl::discover ::bl_static_cache::prepare ::bl_static_cache::publish ::locality_inventory::capture} {
    if {[llength [info commands $command]] != 1} {error "Missing globally sourced production command: $command"}
}
if {[namespace exists ::lb::bl] || [namespace exists ::lb::bl_static_cache]} {error "Backend was loaded in a nested namespace"}
set f [open $code/native_static_discovery_cache_probe.tcl];set probe [read $f];close $f
if {[string first {set plan [lb::discover $out/$mode 16]} $probe] < 0} {error "Native cache probe bypasses the verified lazy loading entry"}
puts "PASS: actual production lazy source loads global backend/cache helpers and native cache probe uses that entry"
