if {[catch {
source [file join [file dirname [info script]] ../../checkpoint_io.tcl]
source [file join [file dirname [info script]] ../../physical_eco.tcl]
lassign $argv input out mode plan_file min_fanout path_limit selection regional_enabled regional_min regional_limit regional_width regional_height regional_budget legacy_mode execution_profile
if {$mode eq ""} {set mode run}
if {$min_fanout eq ""} {set min_fanout 16}
if {$path_limit eq ""} {set path_limit 1000}
source [file join [file dirname [info script]] recovery.tcl]
set resume_boundary ""
if {[string match _resume_* $mode]} {
    set resume_boundary [rfr::admit_resume $mode $input $out $plan_file]
} else {
    if {$mode ni {run inspect edit place route reopen scope_repair}} {error "Unknown mode: $mode"}
    if {[file exists $out]} {error "Refusing to overwrite output: $out"}
    file mkdir $out
}
source [file join [file dirname [info script]] core.tcl]
source [file join [file dirname [info script]] verification_snapshot.tcl]
source [file join [file dirname [info script]] regional.tcl]
source [file join [file dirname [info script]] local_broadcast.tcl]
lb::install
source [file join [file dirname [info script]] execution.tcl]
if {$execution_profile eq ""} {set execution_profile fast}
execopt::configure $execution_profile
if {$regional_enabled eq ""} {set regional_enabled 1}
if {$legacy_mode eq ""} {set legacy_mode run}
if {$legacy_mode ni {run skip}} {error "Unknown legacy mode"}
set options [dict create enabled $regional_enabled]
foreach key {min_fanout branch_limit region_width region_height max_luts} value [list $regional_min $regional_limit $regional_width $regional_height $regional_budget] {
    if {$value ne ""} {dict set options $key $value}
}
rf::configure $options
if {$selection eq ""} {set selection structure}
if {$selection ni {structure timing}} {error "Unknown selection: $selection"}
set sb::selection $selection
set_param general.maxThreads 8
proc phase {name} {
    global out
    set f [open $out/phase.txt w]
    puts $f "[clock seconds]\t$name"
    close $f
    puts "SBECO_PHASE [clock seconds] $name"
    flush stdout
}
proc verify_stage {plan folder placed {reports 0}} {
    # All restores, ECO and physical operations happen outside this read scope.
    vs::with [file tail $folder] {
        sb::verify $plan $folder $placed
        if {[dict exists $plan mobility]} {mobility::verify $plan $folder/mobility}
        if {[dict exists $plan regional]} {
            rf::verify [dict get $plan regional] $folder $placed
            if {$reports} {rf::reports [dict get $plan regional] $folder}
        }
    }
    vs::save $::vs::last_statistics $folder/native_read_reuse.tsv
}
phase open
if {![info exists ::compilefast::active] || !$::compilefast::active} {open_checkpoint $input}
phase spatial_cache
sb::spatial_cache
if {$mode in {run inspect}} {
    phase discovery
    if {$legacy_mode eq "run"} {
        set plan [sb::scan $out $path_limit $min_fanout]
    } else {
        set plan [dict create schema slr-broadcast-eco-v1 counts_before [sb::counts] data {} ce {} fixed {} ff_added 0 lut_added 0 no_op 1 selection structure]
    }
    if {[dict get $rf::config enabled]} {
        phase regional_discovery
        set regional [rf::discover $out [rf::legacy_exclusions $plan]]
        dict set plan regional $regional
        dict set plan regional_lut_added [dict get $regional lut_added]
    }
    sb::save $plan $out/plan.tcl
} else {
    source $plan_file
    set plan $sb_plan
    if {$resume_boundary eq ""} {sb::save $plan $out/plan.tcl}
}
if {$mode eq "inspect"} {
    phase baseline_reports
    sb::reports $plan $out/baseline 0
    execopt::save $out $mode
    phase inspected
    close_design
    exit
}
if {$mode in {run edit}} {
    if {[dict exists $plan regional]} {rf::validate_edit_scope [dict get $plan regional]}
    phase baseline_reports
    sb::reports $plan $out/baseline 0
    if {[dict exists $plan local_broadcast joint_input]} {
        phase joint_baseline_guard
        set plan [ji::capture_guard $plan $out]
        sb::save $plan $out/plan.tcl
    }
    phase apply
    set changed {}
    if {[dict exists $plan local_broadcast]} {
        lappend changed {*}[dict keys [dict get $plan local_broadcast graph moves]]
    } else {
        dict for {name item} [dict get $plan data] {
            foreach slr [dict keys [dict get $item replicas]] {
                lappend changed {*}[dict get $item groups $slr]
            }
        }
    }
    if {[dict exists $plan regional]} {
        foreach root [dict get $plan regional roots] {lappend changed {*}[dict get $root sinks]}
    }
    set physical [plg::capture $changed $out/physical_edit]
    set plan [sb::apply $plan $out]
    if {[dict exists $plan regional]} {
        phase regional_apply
        set regional [rf::apply [dict get $plan regional] $out]
        dict set plan regional $regional
        if {[dict get $regional lut_added] > 0} {dict set plan no_op 0}
        sb::save $plan $out/plan.tcl
        rf::verify $regional $out/after_edit 0
    }
    # Finish geometry-dependent edits first, then free changed FFs before any
    # old buffer's location flags can revalidate an incompatible shared Slice.
    plg::release $physical
    if {[llength [info commands mobility::apply]]} {
        set plan [mobility::apply $plan $out]
        sb::save $plan $out/plan.tcl
    }
    vs::with after_edit {sb::verify $plan $out/after_edit 0}
    vs::save $::vs::last_statistics $out/after_edit/native_read_reuse.tsv
    if {![info exists ::compilefast::active] || !$::compilefast::active || $::compilefast::debug_checkpoints} {write_checkpoint $out/after_edit.dcp}
}
if {$mode eq "scope_repair"} {
    phase scope_repair_preflight
    # Validate the reopened edited netlist before any physical repair.
    verify_stage $plan $out/scope_repair_before 0 0
    source [file join [file dirname [info script]] scope_repair.tcl]
    phase scope_local_legalization
    set plan [scr::repair $plan $out/scope_repair]
    sb::save $plan $out/plan.tcl
    phase update_clock_routing
    update_clock_routing
}
if {$mode in {run edit place scope_repair _resume_post_place}} {
    if {$mode eq "place"} {
        if {[dict exists $plan regional]} {rf::region_constraints [dict get $plan regional] $out/resume_region_constraints 1}
        verify_stage $plan $out/resume_edit 0 0
    }
    if {$resume_boundary eq "" && $mode ne "scope_repair"} {
        phase placement
        if {![dict exists $plan no_op] || ![dict get $plan no_op]} {
            plg::place $out/physical_place -no_psip -no_bufg_opt
            if {[info exists ::sllph::active] && $::sllph::active} {sllph::remove}
            phase update_clock_routing
            update_clock_routing
        } else {
            phase no_structural_changes_keep_existing_placement
        }
        if {[info exists ::sllph::active] && $::sllph::active} {sllph::remove}
        if {[dict exists $plan regional]} {rfr::restore_at_boundary [dict get $plan regional] $out post_place}
    }
    # A recovery process verifies raw reopened properties before any restoration.
    if {$mode in {run edit place} && [dict exists $plan local_broadcast]} {
        source [file join [file dirname [info script]] scope_repair.tcl]
        phase scope_local_legalization
        set plan [scr::repair $plan $out/scope_repair]
        sb::save $plan $out/plan.tcl
    }
    phase post_place_validation
    verify_stage $plan $out/post_place 1 1
    if {$resume_boundary eq "post_place"} {rfr::accept_resume $out $resume_boundary}
    rfr::publish_checkpoint $out post_place $resume_boundary $::execopt::enabled
    sb::reports $plan $out/post_place 0
    set audit_stage placed
    source [file join [file dirname [info script]] ../../control/audit_active.tcl]
    if {[dict exists $plan joint_guard]} {
        phase joint_placed_timing_gate
        ji::placed_guard $plan $out
    }
}
if {$mode in {run edit place scope_repair route _resume_post_place _resume_resume_place _resume_post_route}} {
    if {$mode in {route _resume_resume_place}} {
        if {$resume_boundary eq "" && [dict exists $plan regional]} {rfr::restore_at_boundary [dict get $plan regional] $out resume_place}
        verify_stage $plan $out/resume_place 1 0
        if {$resume_boundary eq "resume_place"} {rfr::accept_resume $out $resume_boundary}
    }
    if {$mode ne "_resume_post_route"} {
        if {[dict exists $plan joint_guard] && ![file exists $out/joint_placed/PASS]} {
            ji::placed_guard $plan $out
        }
        phase physical_route_gate
        plg::before_route $out/physical_pre_route
        phase routing
        route_design
    }
    phase final_reports
    if {$mode ne "_resume_post_route" && [dict exists $plan regional]} {rfr::restore_at_boundary [dict get $plan regional] $out post_route}
    verify_stage $plan $out/post_route 1 1
    if {$resume_boundary eq "post_route"} {rfr::accept_resume $out $resume_boundary}
    rfr::publish_checkpoint $out post_route $resume_boundary $::execopt::enabled
    file mkdir $out/post_route
    report_timing_summary -delay_type min_max -file $out/post_route/timing_summary.rpt
    report_route_status -file $out/post_route/route_status.rpt
    plg::assert_routed $out/post_route/physical_acceptance
    write_xdc $out/applied_constraints.xdc
} elseif {$mode eq "reopen"} {
    phase reopen_validation
    plg::assert_routed $out/physical_acceptance
    verify_stage $plan $out 1 1
    sb::reports $plan $out 1
}
if {$mode eq "reopen"} {
    source [file join [file dirname [info script]] ../../control/final_fanout.tcl]
    experiment_final_fanout $out
    set audit_stage routed
    source [file join [file dirname [info script]] ../../control/audit_active.tcl]
}
execopt::save $out $mode
phase complete
set f [open $out/complete.txt w]
puts $f "Implementation/structural checks complete. Read timing, routing and DRC reports separately."
close $f
close_design
exit
} sb_error sb_options]} {
    if {[dict exists $sb_options -errorcode] && [dict get $sb_options -errorcode] eq {JI TIMING_REJECTED}} {
        puts stderr "JOINT_TIMING_REJECTED $sb_error"
        close_design
        exit 77
    }
    if {[info exists out] && [info exists mode] && [namespace exists ::execopt]} {catch {execopt::save $out $mode}}
    if {[dict exists $sb_options -errorcode] && [dict get $sb_options -errorcode] eq {RF CHECKPOINT_REOPEN_REQUIRED}} {
        puts stderr "SBECO_RECOVERY_REQUIRED $sb_error"
        close_design
        exit 75
    }
    puts stderr "SBECO_ERROR $sb_error"
    puts stderr [dict get $sb_options -errorinfo]
    if {[info exists out] && [file isdirectory $out]} {
        set f [open $out/error.txt w]
        puts $f [dict get $sb_options -errorinfo]
        close $f
    }
    exit 1
}
