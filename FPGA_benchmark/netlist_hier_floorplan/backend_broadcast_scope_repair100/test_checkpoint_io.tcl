set ::threads 8
set ::seen {}
proc get_param {name} {return $::threads}
proc set_param {name value} {set ::threads $value}
proc write_checkpoint {args} {
    lappend ::seen [list $::threads $args]
    if {$::threads != 1} {error "Serialization was not limited"}
    if {[lindex $args end] eq "fail.dcp"} {return -code error -errorcode {NATIVE SAVE} "native serialization failure"}
    return [lindex $args end]
}
set helper [file join [file dirname [info script]] checkpoint_io.tcl]
source $helper
source $helper
set name {safe path with spaces.dcp}
if {[write_checkpoint -force $name] ne $name || $::threads != 8} {error "Success arguments or thread restoration changed"}
set code [catch {write_checkpoint fail.dcp} msg options]
if {!$code || $msg ne "native serialization failure" || [dict get $options -errorcode] ne {NATIVE SAVE} || $::threads != 8} {error "Failure or restoration was hidden"}
set ::threads 4
write_checkpoint last.dcp
if {$::threads != 4 || [llength $::seen] != 3} {error "Duplicate wrapper, retry or wrong restoration"}
puts "PASS: checkpoint success/error propagation, exact arguments, idempotent source and original thread restoration"
