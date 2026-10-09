# Execute the actual production discovery method with a controlled global source.
set f [open [file join [file dirname [info script]] local_broadcast.tcl]]
set source_text [read $f];close $f
set begin [string first {proc lb::discover } $source_text]
set next [string first {
proc } $source_text [expr {$begin+1}]]
set definition [string range $source_text $begin [expr {$next-1}]]
namespace eval lb {variable module_dir /fake}
set ::env(BL_LOCALITY) 1
rename source test_real_source
proc source {path} {
    if {[uplevel 1 {namespace current}] ne "::"} {error wrong_source_namespace}
    namespace eval ::bl {}
    proc ::bl::discover {out min_fanout} {return [list $out $min_fanout]}
}
eval $definition
if {[lb::discover target 16] ne {target 16}} {error discovery_dispatch_failed}
if {![llength [info commands ::bl::discover]]} {error missing_global_backend}
puts "PASS: production lazy discovery sources backend in global namespace"
