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
f96::phase seed_place
place_design
bi_snapshot $out seed_place
f96::phase seed_complete
close_design
exit
