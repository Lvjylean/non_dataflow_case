# Independent seed stage for the batched fanout experiment.
set_param general.maxThreads 8
lassign $argv input checkpoint out
if {[file exists $out]} {error "Refusing to replace seed evidence"}
file mkdir $out
set here [file dirname [file normalize [info script]]]
source $here/../fanout96/core.tcl
source $here/adapter.tcl
bi_load $input
f96::phase open_postopt
open_checkpoint $checkpoint
bi_apply $out
set forced [get_nets -hier -filter {FORCE_MAX_FANOUT > 0}]
if {[llength $forced]} {reset_property FORCE_MAX_FANOUT $forced}
write_xdc $out/floorplan_constraints.xdc
bi_snapshot $out constrained
if {[info exists ::env(COMPILEFAST_SLL_PLAN)]} {
    f96::phase sll_reservation
    sllph::install $::env(COMPILEFAST_SLL_PLAN) $::env(COMPILEFAST_RUN_ROOT)/sll_reservation
}
f96::phase seed_place
plg::place $out/physical_seed
bi_snapshot $out seed_place
f96::phase seed_complete
if {![info exists ::compilefast::active] || !$::compilefast::active} {close_design; exit}
