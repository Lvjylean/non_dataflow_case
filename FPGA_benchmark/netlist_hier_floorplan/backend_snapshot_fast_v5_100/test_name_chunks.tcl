# Reproduce command shadowing while keeping a native-collection path separate.
source [file join [file dirname [info script]] code regional core.tcl]
proc check {ok why} {if {!$ok} {error $why}}
set names [list {top/bus[9]} {top/path with space} {top/{braces}} {top/semicolon;dollar$}]
for {set i 0} {$i < 7000} {incr i} {lappend names top/n$i}
foreach limit {1 17 2048 9000} {
    set flat {};foreach batch [sb::name_chunks $names $limit] {lappend flat {*}$batch}
    check [expr {$flat eq $names}] portable_order_and_complete_names
}
foreach invalid {0 -1 0.5 text} {check [catch {sb::name_chunks $names $invalid}] invalid_limit}
check [expr {[sb::name_chunks {} 5] eq ""}] empty
foreach command {llength lrange lappend} {rename ::$command ::tcl::$command}
proc ::llength {items} {if {$items eq "NATIVE_COLLECTION"} {return 7001};return [::tcl::llength $items]}
proc ::lrange {items first last} {
    if {$items ne "NATIVE_COLLECTION"} {error "ordinary list reached Vivado wrapper"}
    incr ::native_ranges
    return [list collection_slice $first $last]
}
proc ::lappend {var args} {upvar 1 $var local;return [::tcl::lappend local {*}$args]}
set native_ranges 0
set chunks [sb::chunks NATIVE_COLLECTION 2048]
check [expr {$native_ranges == 4 && [llength $chunks] == 4}] native_collection_not_converted
set flat {};foreach batch [sb::name_chunks $names 2048] {lappend flat {*}$batch}
check [expr {$flat eq $names && $native_ranges == 4}] bypass_reloaded_range_only_for_names
puts "NAME_CHUNKS_PASS names=[llength $names] native_batches=$native_ranges"
