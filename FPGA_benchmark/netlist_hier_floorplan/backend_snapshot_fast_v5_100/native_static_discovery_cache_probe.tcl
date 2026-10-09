# Three fresh native processes, in order: live, fresh, cached.
# -tclargs CODE OUT MODE FIXTURE_BEFORE_DCP
# No netlist edit, placement or routing is performed by this probe.
if {[catch {
lassign $argv code out mode checkpoint
set code [file normalize $code];set out [file normalize $out]
if {$mode ni {live fresh cached}} {error "Expected live/fresh/cached"}
if {[file exists $out/$mode]} {error "Refusing to overwrite cache probe evidence"}
file mkdir $out/$mode
set ::env(BL_LOCALITY) 1
set ::env(BL_STATIC_CACHE_ENABLED) 1
set ::env(COMPILEFAST_RUN_ROOT) $out
unset -nocomplain ::env(BL_STATIC_CACHE_SOURCE) ::env(JI_EXCLUDE)
source $code/checkpoint_io.tcl
source $code/physical_eco.tcl
source $code/code/regional/core.tcl
source $code/code/regional/regional.tcl
source $code/code/regional/local_broadcast.tcl
lb::install
execopt::configure fast
set_param general.maxThreads 8
set ::input $out/base/pre_route.dcp
if {$mode eq "live"} {
    if {[file exists $::input]} {error "Refusing to overwrite cache probe checkpoint"}
    file mkdir $out/base
    exec python3 $code/verify_static_discovery_cache_probe.py manifest $code $out
    open_checkpoint $checkpoint
    # Preserve the actual in-memory state at the writer boundary, then collect
    # without reopening, matching the normal chained base -> generic boundary.
    write_checkpoint $::input
    namespace eval compilefast {variable active 1}
} else {
    open_checkpoint $::input
    set ::env(JI_EXCLUDE) $out/exclude.json
    if {$mode eq "cached"} {set ::env(BL_STATIC_CACHE_SOURCE) $out/live/locality}
}
sb::spatial_cache
set discovery_begin [clock milliseconds]
set plan [lb::discover $out/$mode 16]
set discovery_ms [expr {[clock milliseconds]-$discovery_begin}]
sb::save $plan $out/$mode/native_plan.tcl
set f [open $out/$mode/native_context.tsv w]
puts $f "key\tvalue"
foreach {key value} [list mode $mode vivado_version [version -short] part [get_property PART [current_design]] \
    checkpoint $::input discovery_ms $discovery_ms] {puts $f "$key\t$value"}
close $f
if {$mode eq "live"} {exec python3 $code/verify_static_discovery_cache_probe.py exclude $code $out}
set f [open $out/$mode/NATIVE_COMPLETE w];puts $f [list mode $mode version [version -short] part [get_property PART [current_design]]];close $f
close_design
if {$mode eq "cached"} {puts [exec python3 $code/verify_static_discovery_cache_probe.py compare $code $out]}
} message options]} {
    puts stderr [dict get $options -errorinfo]
    exit 1
}
exit 0
