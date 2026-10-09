# Read-only checkpoint preflight: change and restore properties only in memory.
# Never applies the saved ECO plan, places, routes or writes a checkpoint.
if {[catch {
lassign $argv code out checkpoint plan_path expected_checkpoint_sha expected_plan_sha
file mkdir $out
if {[file exists $out/PASS]} {error "Refusing to overwrite completed preflight"}
proc file_sha {path} {return [lindex [exec sha256sum $path] 0]}
if {[file_sha $checkpoint] ne $expected_checkpoint_sha || [file_sha $plan_path] ne $expected_plan_sha} {
    error "Checkpoint or saved plan hash changed"
}
set ::env(BL_LOCALITY) 1
source $code/checkpoint_io.tcl
source $code/physical_eco.tcl
source $code/code/regional/core.tcl
source $code/code/regional/regional.tcl
source $code/code/regional/local_broadcast.tcl
lb::install
execopt::configure fast
set_param general.maxThreads 8
open_checkpoint $checkpoint
source $plan_path
sb::require [expr {![llength [get_cells -quiet sbeco_local_*]]}] "Input contains partial ECO replicas"
set local [dict get $sb_plan local_broadcast]
set graph [dict get $local graph]
set snapshot [dict get $local snapshot]
dict for {key net} [dict get $snapshot nets] {
    if {[dict get $net kind] eq "ordinary"} {
        sb::require [expr {[sb::loads [dict get $net anchor]] eq [dict get $net before]}] "Stale saved boundary: $key"
    }
}
dict for {key root} [dict get $snapshot roots] {
    sb::require [expr {[sb::config [dict get $root cell]] eq [dict get $root config]}] "Stale primitive: $key"
}
# Independently derive every old net segment from moved pins before unlocking.
set moved_pins [dict keys [dict get $graph moves]]
array set old_segments {}
foreach batch [sb::chunks $moved_pins 512] {
    set pins [execopt::exact_objects pin $batch]
    foreach name [sb::names [get_nets -quiet -segments -of_objects $pins]] {set old_segments($name) 1}
}
array set before_properties {}
set protected 0
foreach batch [sb::chunks [array names old_segments] 512] {
    set objects [execopt::exact_objects net $batch]
    foreach name [sb::names $objects] value [sb::values DONT_TOUCH $objects] {
        set before_properties($name) $value
        if {[sb::one_bit $value]} {incr protected}
    }
}
sb::require [expr {$protected>0}] "Real regression must contain protected moved-net segments"
set boundary [lb::unlock_boundaries $local]
foreach name [array names old_segments] {
    sb::require [dict exists $boundary properties net $name] "Old segment omitted from unlock: $name"
}
foreach batch [sb::chunks [array names old_segments] 512] {
    set objects [execopt::exact_objects net $batch]
    foreach name [sb::names $objects] value [sb::values DONT_TOUCH $objects] {
        sb::require [expr {![sb::one_bit $value]}] "Protected old net remains locked: $name"
    }
}
lb::restore_boundaries [dict get $boundary properties]
dict for {kind values} [dict get $boundary properties] {
    foreach batch [sb::chunks [dict keys $values] 512] {
        set objects [execopt::exact_objects $kind $batch]
        foreach name [sb::names $objects] value [sb::values DONT_TOUCH $objects] {
            sb::require [expr {$value eq [dict get $values $name]}] "Protection not restored: $kind $name"
        }
    }
}
if {[file_sha $checkpoint] ne $expected_checkpoint_sha || [file_sha $plan_path] ne $expected_plan_sha} {
    error "Preflight input changed on disk"
}
set f [open $out/summary.tsv w]
puts $f "key\tvalue"
foreach {key value} [list status PASS moved_pins [llength $moved_pins] old_segments [array size old_segments] protected_old_segments $protected unlocked_cells [dict size [dict get $boundary properties cell]] unlocked_nets [dict size [dict get $boundary properties net]] checkpoint_sha256 $expected_checkpoint_sha plan_sha256 $expected_plan_sha source $code modified_connections 0 wrote_checkpoint 0] {puts $f "$key\t$value"}
close $f
set f [open $out/PASS w];puts $f "PASS real GETRF complete old-net protection coverage and restoration; no ECO or checkpoint write";close $f
close_design
exit
} message options]} {puts stderr [dict get $options -errorinfo];exit 1}
