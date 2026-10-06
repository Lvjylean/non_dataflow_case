# Admission only: preserve every physical procedure, argv and native source path.
namespace eval phase_memory {variable last ""}
proc phase_memory::admit {stage} {
    variable last
    if {$last eq $stage} {return}
    puts "PHASE_MEMORY waiting stage=$stage [clock seconds]"
    flush stdout
    set receipt [exec python3 $::env(PHASE_GATE_TOOL) --directory $::env(PHASE_GATE_DIR) --stage $stage 2>@1]
    puts "PHASE_MEMORY granted stage=$stage $receipt"
    flush stdout
    set last $stage
}
proc phase_memory::before_source {command operation} {
    # Tcl's source supports -encoding; the final word is always the source file.
    set path [file normalize [lindex $command end]]
    set flow [file normalize $::env(PHASE_FLOW_ROOT)]
    if {$path eq "$flow/code/base/balanced_implementation/seed_fast.tcl"} {
        phase_memory::admit seed
    } elseif {$path eq "$flow/code/base/balanced_implementation/implement_pre_route.tcl"} {
        phase_memory::admit base
    } elseif {$path eq "$flow/code/regional/run.tcl"} {
        set stage generic
        if {[lindex $::argv 2] eq "reopen"} {set stage reopen}
        phase_memory::admit $stage
    }
}
trace add execution source enter ::phase_memory::before_source
source $::env(PHASE_NATIVE_SCRIPT)
