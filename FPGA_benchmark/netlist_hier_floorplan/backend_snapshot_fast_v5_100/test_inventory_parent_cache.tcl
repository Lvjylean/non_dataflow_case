# Exact old/new hierarchy-protection behavior with a counted native mock.
source [file join [file dirname [info script]] code regional core.tcl]
source [file join [file dirname [info script]] code regional regional.tcl]
source [file join [file dirname [info script]] code regional locality_inventory.tcl]
array set parents {top 1 top/free 0 top/near 1 free 0 free/deep 0}
set queries 0
proc get_cells {args} {
    global parents
    set n [lindex [lindex $args end] 0]
    if {![info exists parents($n)]} {return {}}
    return [list $n]
}
proc get_property {property objects} {
    global parents queries
    if {$property ne "DONT_TOUCH"} {error "Unexpected property $property"}
    incr queries
    return $parents([lindex $objects 0])
}
proc check {ok why} {if {!$ok} {error $why}}
set cases {root top top/free/lut top/near/lut free/deep/lut}
for {set i 0} {$i<1000} {incr i} {lappend cases top/free/sibling_$i}
array unset ::rf::ancestor_cache *
set old {};foreach c $cases {dict set old $c [rf::protected_ancestor $c]}
set old_queries $queries
locality_inventory::reset_protection
set queries 0
set fast {};foreach c $cases {dict set fast $c [locality_inventory::protected_ancestor $c]}
check [expr {$old eq $fast}] exact_results
check [expr {$queries==5 && $queries<$old_queries}] unique_parent_queries
check [expr {[dict get $fast root] eq "" && [dict get $fast top] eq ""}] excludes_self
check [expr {[dict get $fast top/near/lut] eq "top/near"}] nearest_parent
check [expr {[dict get $fast top/free/lut] eq "top"}] nearest_protected_ancestor
# Unknown parent must fail in both implementations with the original message.
array unset ::rf::ancestor_cache *
set old_rc [catch {rf::protected_ancestor missing/lut} old_error]
locality_inventory::reset_protection
set new_rc [catch {locality_inventory::protected_ancestor missing/lut} new_error]
check [expr {$old_rc && $new_rc && $old_error eq $new_error}] missing_parent
# Each immutable snapshot starts over after protection changes.
set parents(top) 0
locality_inventory::reset_protection
check [expr {[locality_inventory::protected_ancestor top/free/lut] eq ""}] stage_reset
set parents(top/free) 1
locality_inventory::reset_protection
check [expr {[locality_inventory::protected_ancestor top/free/lut] eq "top/free"}] changed_nearest_parent
puts "PARENT_CACHE_PASS cases=[llength $cases] old_native_queries=$old_queries optimized_native_queries=5"
