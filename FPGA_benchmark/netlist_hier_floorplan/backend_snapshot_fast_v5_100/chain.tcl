# Preserve three physical placements and one full route, sharing the live design.
if {[catch {
namespace eval compilefast {variable active 1; variable debug_checkpoints 0}
lassign $argv compilefast_input compilefast_checkpoint compilefast_output
set compilefast_code [file dirname [file normalize [info script]]]
file mkdir $compilefast_output
set compilefast_events [open $compilefast_output/chain_events.tsv w]
puts $compilefast_events "stage\tevent\tepoch_ms"
proc compilefast_event {stage event} {
    puts $::compilefast_events "$stage\t$event\t[clock milliseconds]"; flush $::compilefast_events
    puts "COMPILEFAST $stage $event [clock seconds]"; flush stdout
}
source $compilefast_code/checkpoint_io.tcl
source $compilefast_code/clock.tcl
source $compilefast_code/sll_balance.tcl
rename open_checkpoint compilefast_open_checkpoint
proc open_checkpoint {args} {
    set result [uplevel 1 [linsert $args 0 compilefast_open_checkpoint]]
    set stale [get_cells -hier -quiet -filter {NAME =~ f96_identity_* || NAME =~ sbeco_* || NAME =~ rfd_lut_* || NAME =~ hfg_identity_* || NAME =~ sllph_*}]
    set forced [get_nets -hier -quiet -filter {FORCE_MAX_FANOUT > 0}]
    set pblocks [get_pblocks -quiet *]
    set f [open $::out/clean_input.tsv w]
    puts $f "check\tcount"
    puts $f "custom_eco_cells\t[llength $stale]"
    puts $f "active_force_max_fanout\t[llength $forced]"
    puts $f "preexisting_pblocks\t[llength $pblocks]"
    close $f
    if {[llength $stale] || [llength $forced] || [llength $pblocks]} {error "Input is not clean post-opt"}
    compilefast_clock $::out 1
    return $result
}
compilefast_event seed begin
set argv [list $compilefast_input $compilefast_checkpoint $compilefast_output/seed]
source $compilefast_code/code/base/balanced_implementation/seed_fast.tcl
rename open_checkpoint {}
rename compilefast_open_checkpoint open_checkpoint
compilefast_event seed end
compilefast_event base begin
set argv [list $compilefast_input $compilefast_output/seed/seed_place.dcp $compilefast_output/base seed $compilefast_output/seed]
source $compilefast_code/code/base/balanced_implementation/implement_pre_route.tcl
compilefast_event base end
namespace delete ::f96
namespace delete ::perf
# Release the first-stage caches before constructing the second-stage plan.
foreach name {cf_owner cf_resource cf_ref cf_members} {array unset ::$name}
compilefast_event generic begin
close $compilefast_events
set argv [list $compilefast_output/base/pre_route.dcp $compilefast_output/generic/implementation run {} 16 1000 structure 1 16 96 2 2 50000 run fast]
source $compilefast_code/code/regional/run.tcl
} message options]} {
    puts stderr [dict get $options -errorinfo]
    exit 1
}
