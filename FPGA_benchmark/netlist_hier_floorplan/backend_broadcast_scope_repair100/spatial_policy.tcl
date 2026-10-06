# Pure, deterministic placement windows; all coordinates are clock regions.
namespace eval geo {}
proc geo::xy {cr} {
    if {![regexp {^X([0-9]+)Y([0-9]+)$} $cr unused x y]} {error "Invalid CR: $cr"}
    return [list $x $y]
}
proc geo::median {values} {
    set values [lsort -integer $values]
    if {![llength $values]} {error "Empty spatial distribution"}
    return [lindex $values [expr {([llength $values]-1)/2}]]
}
proc geo::window {regions grid {radius 1}} {
    set xs {}; set ys {}; set slrs {}
    foreach cr $regions {
        if {![dict exists $grid $cr]} {error "Unknown CR in device grid: $cr"}
        lassign [xy $cr] x y
        lappend xs $x; lappend ys $y; lappend slrs [dict get $grid $cr]
    }
    set slrs [lsort -unique $slrs]
    if {[llength $slrs] != 1} {error "A local window cannot span SLRs"}
    set cx [median $xs]; set cy [median $ys]; set allowed {}
    dict for {cr slr} $grid {
        lassign [xy $cr] x y
        if {$slr eq [lindex $slrs 0] && abs($x-$cx)<=$radius && abs($y-$cy)<=$radius} {lappend allowed $cr}
    }
    if {![llength $allowed]} {error "Empty device-clipped placement window"}
    return [lsort -dictionary $allowed]
}
proc geo::rectangle {regions} {
    set xs {}; set ys {}
    foreach cr $regions {lassign [xy $cr] x y; lappend xs $x; lappend ys $y}
    set xs [lsort -integer $xs]; set ys [lsort -integer $ys]; set result {}
    for {set x [lindex $xs 0]} {$x <= [lindex $xs end]} {incr x} {
        for {set y [lindex $ys 0]} {$y <= [lindex $ys end]} {incr y} {lappend result X${x}Y${y}}
    }
    return $result
}

proc geo::expand_ranges {ranges} {
    set result {}
    foreach range $ranges {
        if {![regexp {^CLOCKREGION_(X[0-9]+Y[0-9]+):(?:CLOCKREGION_)?(X[0-9]+Y[0-9]+)$} $range unused first last]} {
            error "Unsupported clock-region range representation: $range"
        }
        lassign [xy $first] x0 y0; lassign [xy $last] x1 y1
        if {$x0>$x1 || $y0>$y1} {error "Reversed clock-region range: $range"}
        for {set x $x0} {$x<=$x1} {incr x} {for {set y $y0} {$y<=$y1} {incr y} {lappend result X${x}Y${y}}}
    }
    return [lsort -unique -dictionary $result]
}
