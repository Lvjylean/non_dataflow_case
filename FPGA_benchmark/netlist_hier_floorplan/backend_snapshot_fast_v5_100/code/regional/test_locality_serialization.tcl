source [file join [file dirname [info script]] locality_backend.tcl]
set encoded {"sinks[0].r/D" "sinks[100].r/D" "sinks[10].r/D"}
set expected [lsort -unique [list {sinks[0].r/D} {sinks[100].r/D} {sinks[10].r/D}]]
if {$encoded eq $expected} {error "Fixture must expose different valid Tcl list encodings"}
set graph [bl::canonical_graph [dict create expected [dict create copy/O $encoded]]]
if {[dict get $graph expected copy/O] ne $expected} {error "Canonical graph mismatch"}
if {![catch {bl::canonical_graph [dict create expected [dict create copy/O {a/D a/D}]]} why] || $why ne "duplicate_planned_sink:copy/O"} {error "Duplicate planned sinks accepted"}
puts "PASS: quoted Python/Tcl list equivalence, brackets, exact canonical sinks, duplicate rejection"
