# Preserve all physical audit products while reusing an already open design.
if {[info exists ::env(COMPILEFAST_SLL_PLAN)]} {
    source [file join [file dirname [info script]] .. sll_balance.tcl]
    sllph::assert_absent
    if {$audit_stage eq "routed"} {sllph::routed_usage [file join $out sll_usage]}
}
set saved_argv $argv
set saved_out $out
set saved_plan $plan
set experiment_root [file normalize [file join [file dirname [info script]] ..]]
set checkpoint [expr {$audit_stage eq "placed" ? "$out/post_place.dcp" : "$out/../implementation/post_route.dcp"}]
set audit_out [file normalize [file join $out .. audit_$audit_stage]]
set argv [list $checkpoint $audit_out $::env(EXPERIMENT_INPUT) $audit_stage]
set audit_reuse_design 1
source $experiment_root/audit.tcl
set audit_reuse_design 0
set argv $saved_argv
set out $saved_out
set plan $saved_plan
unset saved_argv saved_out saved_plan
