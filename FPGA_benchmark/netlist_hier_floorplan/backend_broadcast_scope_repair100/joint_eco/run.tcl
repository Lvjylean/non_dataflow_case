if {[catch {
lassign $argv root input plan_file prior_file spec_file out mode cert_file
file mkdir $out
set code [file dirname [info script]];set flow [file join $root flow]
source $flow/checkpoint_io.tcl
source [file join $code ../physical_eco.tcl]
source $flow/code/regional/core.tcl
source $flow/code/regional/regional.tcl
source $flow/code/regional/local_broadcast.tcl
source $code/joint.tcl
lb::install
source $code/read_cache.tcl
fc::install
execopt::configure fast
set_param general.maxThreads 8
proc phase {name} {
    global out
    set f [open $out/phase.txt w];puts $f "[clock seconds]\t$name";close $f
    set f [open $out/events.tsv a];puts $f "[clock seconds]\t$name";close $f
    puts "JOINT_PHASE [clock seconds] $name";flush stdout
}
phase open
open_checkpoint $input
sb::require [expr {abs([get_property PERIOD [get_clocks ap_clk]]-6.7)<1e-6}] "Period mismatch"
source $plan_file;set plan $sb_plan;unset sb_plan
if {$mode eq "implement"} {
    source $prior_file;set prior $target_certificate;unset target_certificate
    source $spec_file
    phase prepare
    set prep_names [fc::names_for $plan $jc_spec $prior]
    fc::with prepare $out $prep_names {set cert [jc::prepare $jc_spec $prior $out]}
    set verify_names [fc::names_for $plan $jc_spec $prior 1]
    unset jc_spec prior
    phase baseline_guard_capture
    set guard [jc::guard_pins $cert]
    source $root/protected_originals.tcl
    set guard [lsort -unique [concat $guard $protected_original_pins]]
    dict set cert guard $guard
    jc::save jc_certificate $cert $out/certificate.tcl
    jc::reports $cert $guard $out/before
    set plan [jc::augment $plan $cert]
    phase apply
    set physical [plg::capture [dict keys [dict get $cert spec changes]] $out/physical_edit]
    jc::apply $cert $out
    plg::release $physical
    sb::save $plan $out/plan.tcl
    phase after_edit_validation
    fc::with after_edit $out $verify_names {
    jc::verify $cert $out/after_edit 0
    sb::verify $plan $out/after_edit 0
    mobility::verify $plan $out/after_edit/mobility
    if {[dict exists $plan regional]} {rf::verify [dict get $plan regional] $out/after_edit 0}
    }
    write_checkpoint $out/after_edit.dcp
    phase physical_memory_admission
    puts [exec python3 $code/memory_gate.py $root $out physical [pid]]
    phase placement
    plg::place $out/physical_place -no_psip -no_bufg_opt
    update_clock_routing
    phase post_place_validation
    fc::with post_place $out $verify_names {
    jc::verify $cert $out/post_place 1
    sb::verify $plan $out/post_place 1
    mobility::verify $plan $out/post_place/mobility
    if {[dict exists $plan regional]} {rf::verify [dict get $plan regional] $out/post_place 1}
    }
    jc::reports $cert $guard $out/post_place
    write_checkpoint $out/post_place.dcp
    set gate [exec python3 $code/gates.py $out/before $out/post_place $root/protected_originals.json $out/post_place/acceptance.json]
    if {$gate ne "ACCEPT"} {
        phase rejected_before_route
        set f [open $out/REJECTED_BEFORE_ROUTE w];puts $f "Timing protection rejected candidate; preserved placement and input checkpoint, no routing performed.";close $f
        close_design;exit
    }
    phase physical_route_gate
    plg::before_route $out/physical_pre_route
    phase routing
    route_design
    set report_out $out/post_route
} elseif {$mode eq "reopen"} {
    source $cert_file;set cert $jc_certificate;unset jc_certificate
    set guard [dict get $cert guard];set report_out $out
    set verify_names [fc::names_for $plan [dict get $cert spec] [dict create clones [dict get $cert inherited]] 1]
} else {error "Unknown mode $mode"}
phase final_validation
fc::with final_validation $out $verify_names {
jc::verify $cert $report_out 1
sb::verify $plan $report_out 1
mobility::verify $plan $report_out/mobility
if {[dict exists $plan regional]} {rf::verify [dict get $plan regional] $report_out 1}
}
source $flow/control/final_fanout.tcl
experiment_final_fanout $report_out
jc::reports $cert $guard $report_out
lb::reports $plan $report_out
report_utilization -file $report_out/utilization.rpt
report_utilization -slr -file $report_out/utilization_slr.rpt
report_timing -max_paths 1000 -nworst 1 -file $report_out/worst1000.rpt
report_drc -file $report_out/drc.rpt
if {$mode eq "implement"} {write_checkpoint $out/post_route.dcp}
plg::assert_routed $report_out/physical_acceptance
if {$mode eq "reopen"} {
    set ::env(EXPERIMENT_INPUT) [file normalize [file join $root inputs]]
    set ::env(COMPILEFAST_PERIOD) 6.7
    set audit_stage routed;source $flow/control/audit_active.tcl
}
phase complete
set f [open $out/complete.txt w];puts $f "PASS execution and structural checks; timing acceptance separate";close $f
close_design;exit
} msg opts]} {
    puts stderr [dict get $opts -errorinfo]
    if {[info exists out]} {set f [open $out/error.txt w];puts $f [dict get $opts -errorinfo];close $f}
    exit 1
}
