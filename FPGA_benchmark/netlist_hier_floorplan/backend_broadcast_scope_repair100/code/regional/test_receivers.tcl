source [file join [file dirname [info script]] core.tcl]
rename sb::prefetch sb::native_prefetch
rename sb::position sb::native_position
set position_calls {}
proc sb::prefetch {names} {set ::prefetched $names}
proc sb::position {name} {
    lappend ::position_calls $name
    return [dict get $::fixture_positions $name]
}
set fixture_positions [dict create ram0 {loc URAM288_X0Y0 bel URAM288 slr SLR1} \
    ram1 {loc URAM288_X0Y1 bel URAM288 slr SLR1} \
    {receiver[0]} {loc SLICE_X0Y0 bel AFF slr SLR1}]
set plan [dict create data [dict create source0 [dict create helpers [dict create \
    h0 [dict create leaves {ram0/DIN_A[0] ram1/DIN_A[0]}] \
    h1 [dict create leaves {ram0/DIN_A[1] receiver[0]/D}]]] \
    source1 [dict create helpers [dict create \
    h2 [dict create leaves {ram1/DIN_B[0] ram0/DIN_B[0]}]]]] \
    fixed [dict create h0 {loc SLICE_X1Y1 bel A6LUT slr SLR1}] ff_added 2]
set expected [dict get $plan fixed]
dict for {c item} [dict get $plan data] {
    dict for {h v} [dict get $item helpers] {
        foreach p [dict get $v leaves] {
            set leaf [file dirname $p]
            dict set expected $leaf [dict get $fixture_positions $leaf]
        }
    }
}
set result [sb::capture_receivers $plan]
sb::require [expr {[dict get $result fixed] eq $expected}] "Exact ordered fixed-cell mapping changed"
sb::require [expr {[dict get $result data] eq [dict get $plan data]}] "Data plan changed"
sb::require [expr {$prefetched eq {ram0 ram1 {receiver[0]}}}] "First-visit order or deduplication changed"
sb::require [expr {$position_calls eq $prefetched}] "Each receiving cell must be captured exactly once"
set bad $plan
dict set bad data ram0 [dict create helpers {}]
set failed [catch {sb::capture_receivers $bad} message]
sb::require [expr {$failed && [string match {*also a frozen sink: ram0} $message]}] "Source/sink overlap guard was lost"
puts "PASS: shared multi-bit RAM receivers, ordered exact fixed mapping, source overlap guard"
