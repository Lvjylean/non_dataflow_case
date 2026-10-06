if {[catch {
set code [file dirname [info script]]
foreach path [lsort [glob -directory $code test_*.tcl]] {
    puts "NATIVE_UNIT [file tail $path]"
    set child [interp create]
    interp eval $child [list source $path]
    interp delete $child
}
puts NATIVE_UNIT_PASS
exit
} message options]} {
puts stderr [dict get $options -errorinfo]
exit 1
}
