source [file join [file dirname [info script]] code/regional/scope_repair.tcl]
namespace eval sb {}
proc sb::require {ok msg} {if {!$ok} {error $msg}}
# Preflight budget and unsupported cone must fail before any physical edits.
set over {};for {set i 0} {$i<33} {incr i} {dict set over cell$i {}}
if {![catch {scr::preflight $over} msg] || ![string match *budget* $msg]} {error "Missing bounded repair admission"}
proc sb::cell {n} {return $n}
proc sb::ref {n} {return MUXF7}
if {![catch {scr::preflight [dict create mux [dict create target SLR0 loc SLICE_X1Y1]]} msg] || ![string match *independent* $msg]} {error "Unsupported cone repair admitted"}
if {[scr::xy SLICE_X12Y34] ne {12 34}} {error "Coordinate parse"}
if {![catch {scr::xy RAMB36_X0Y0}]} {error "Non-Slice repair admitted"}
puts "PASS scope repair bounded admission and supported resource contract"
