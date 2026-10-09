# Read-only proof on one placed checkpoint: CODE CHECKPOINT OUT.
# Every complete candidate table and actual native plan must match reference.
if {[catch {
lassign $argv code checkpoint out
set code [file normalize $code];set out [file normalize $out]
if {[file exists $out]} {error "Refusing to overwrite candidate proof evidence"}
file mkdir $out
set ::env(BL_LOCALITY) 1
set ::env(BL_STATIC_CACHE_ENABLED) 0
unset -nocomplain ::env(BL_STATIC_CACHE_SOURCE) ::env(JI_EXCLUDE)
source $code/checkpoint_io.tcl
source $code/physical_eco.tcl
source $code/code/regional/core.tcl
source $code/code/regional/regional.tcl
source $code/code/regional/local_broadcast.tcl
source $code/code/regional/locality_backend.tcl
lb::install
execopt::configure fast
set_param general.maxThreads 8
open_checkpoint $checkpoint
namespace eval candidate_proof {variable mode {};variable calls {}}
proc candidate_proof::count {command operation} {dict incr ::candidate_proof::calls [namespace tail [lindex $command 0]]}
# Force an epoch mismatch only at the snapshot boundary. The underlying native
# database is unchanged; the stale connection view must produce no hit.
rename locality_inventory::connection_load locality_inventory::connection_load_original
proc locality_inventory::connection_load {folder} {
    if {$::candidate_proof::mode ne "stale"} {return [connection_load_original $folder]}
    set saved $::locality_inventory::capture_epoch
    incr ::locality_inventory::capture_epoch -1
    set rc [catch {connection_load_original $folder} result options]
    set ::locality_inventory::capture_epoch $saved
    if {$rc} {return -options $options $result}
    return $result
}
foreach mode {reference enabled stale} {
    set ::candidate_proof::mode $mode
    set ::env(BL_INPUT_REUSE_MODE) [expr {$mode eq "reference" ? "reference" : "enabled"}]
    set ::candidate_proof::calls {}
    set traced {}
    foreach command {get_cells get_pins get_nets get_property get_clocks get_ports get_sites get_slrs get_clock_regions get_timing_paths} {
        if {[namespace which -command ::$command] ne ""} {
            trace add execution ::$command enter ::candidate_proof::count;lappend traced ::$command
        }
    }
    file mkdir $out/$mode
    set tick [clock microseconds]
    set rc [catch {bl::discover $out/$mode 16} plan options]
    set elapsed [expr {[clock microseconds]-$tick}]
    foreach command $traced {trace remove execution $command enter ::candidate_proof::count}
    if {$rc} {return -options $options $plan}
    sb::save $plan $out/$mode/native_plan.tcl
    set f [open $out/$mode/native_calls.tsv w];puts $f "key\tvalue"
    dict for {key value} $::candidate_proof::calls {puts $f "$key\t$value"}
    puts $f "elapsed_us\t$elapsed";close $f
    set f [open $out/$mode/NATIVE_COMPLETE w]
    puts $f [dict create mode $mode version [version -short] part [get_property PART [current_design]] checkpoint $checkpoint]
    close $f
}
close_design
puts [exec python3 $code/verify_candidate_readback_v2.py $code $out]
} message options]} {puts stderr [dict get $options -errorinfo];exit 1}
exit 0
