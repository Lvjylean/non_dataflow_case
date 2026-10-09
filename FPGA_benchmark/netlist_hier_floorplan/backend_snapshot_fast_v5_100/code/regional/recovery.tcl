# A bounded checkpoint handoff, not a general error retry or a background monitor.
namespace eval rfr {
    variable boundaries {post_place resume_place post_route}
}
proc rfr::restore_at_boundary {plan out boundary} {
    variable boundaries
    if {$boundary ni $boundaries} {error "Unknown protection boundary: $boundary"}
    set rc [catch {rf::restore_native_lut_protection $plan $out/${boundary}_protection} message options]
    if {!$rc} {return $message}
    if {![dict exists $options -errorcode] || [dict get $options -errorcode] ne {RF NATIVE_LUT_PROTECTION_STICKY}} {
        return -options $options $message
    }
    set checkpoint $out/recovery/$boundary.dcp
    if {[file exists $checkpoint]} {error "Refusing repeated recovery at $boundary"}
    file mkdir $out/recovery
    # The checkpoint remains diagnostic until the fresh process passes all checks.
    write_checkpoint $checkpoint
    set f [open $out/recovery/pending.txt w]
    puts $f $boundary
    close $f
    return -code error -errorcode {RF CHECKPOINT_REOPEN_REQUIRED} $message
}
proc rfr::admit_resume {mode input out plan_file} {
    variable boundaries
    set boundary [string range $mode [string length _resume_] end]
    if {$boundary ni $boundaries} {error "Unknown checkpoint resume mode: $mode"}
    set request $out/recovery/pending.txt
    if {![file isfile $request]} {error "Missing checkpoint recovery request"}
    set f [open $request r]
    set requested [string trim [read $f]]
    close $f
    if {$requested ne $boundary} {error "Checkpoint recovery boundary mismatch"}
    foreach actual [list $input $plan_file] expected [list $out/recovery/$boundary.dcp $out/plan.tcl] {
        if {![file isfile $actual] || [file normalize $actual] ne [file normalize $expected]} {
            error "Checkpoint recovery input/plan mismatch: $actual"
        }
    }
    if {[file exists $out/complete.txt] || [file exists $out/recovery/${boundary}_attempted.txt]} {
        error "Refusing completed or repeated checkpoint recovery"
    }
    set f [open $out/recovery/${boundary}_attempted.txt w]
    puts $f "[clock seconds]\tFresh-process acceptance required; no placement/routing replay."
    close $f
    return $boundary
}
proc rfr::accept_resume {out boundary} {
    # Called only after the unchanged full structure/protection/location checks.
    set f [open $out/recovery/${boundary}_accepted.txt w]
    puts $f "[clock seconds]\tPASS: raw reopened design passed full checks."
    close $f
    file delete $out/recovery/pending.txt
}
proc rfr::publish_checkpoint {out boundary resume_boundary reuse} {
    set target $out/$boundary.dcp
    if {!$reuse || $resume_boundary ne $boundary} {
        execopt::timed write_checkpoint [list write_checkpoint $target]
        return
    }
    # Only the raw reopened, fully verified, unmodified recovery design qualifies.
    # No design mutation is allowed between admission, validation and this call.
    set source $out/recovery/$boundary.dcp
    set accepted $out/recovery/${boundary}_accepted.txt
    if {$boundary ni {post_place post_route} || ![file isfile $accepted] ||
        ![file isfile $source] || [file size $source] == 0 || [file exists $target]} {
        error "Checkpoint publication is not eligible: $boundary"
    }
    if {[llength $::execopt::pending] || [llength $::execopt::region_order]} {
        error "Pending design edits prevent checkpoint reuse"
    }
    # Copy, rather than hard-link, so later consumers cannot alter diagnostic bytes.
    set temporary ${target}.copying
    execopt::timed copy_verified_checkpoint [list file copy $source $temporary]
    file rename $temporary $target
    set f [open $out/recovery/${boundary}_published.tsv w]
    puts $f "boundary\tsource\ttarget\tbytes"
    puts $f "$boundary\t$source\t$target\t[file size $target]"
    close $f
}
