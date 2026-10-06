# Read-only active macro timing graph, including Vivado's expanded DSP internals.
# Usage: vivado -mode batch -source this.tcl -tclargs post_opt.dcp raw/cells.tsv NEW_DIR
set_param general.maxThreads 4
proc vals {p objects} {
 if {![llength $objects]} {return {}}
 set v [get_property $p $objects]
 if {[llength $objects]==1} {return [list $v]}
 return $v
}
proc say {s} {puts "MACRO_TIMING [clock seconds] $s"; flush stdout}
proc macro_main {argv} {
set dcp [lindex $argv 0]; set cellsfile [lindex $argv 1]; set out [lindex $argv 2]
if {[file exists $out]} {error "Refusing to overwrite $out"}
file mkdir $out
set provenance [open $out/input_binding.tsv w]
puts $provenance "kind\tpath\tsha256"
foreach kind {dcp cells extractor} path [list $dcp $cellsfile [info script]] {
 puts $provenance "$kind\t[file normalize $path]\t[lindex [exec sha256sum $path] 0]"
}
close $provenance
array set ids {}; array set refs {}
set f [open $cellsfile r]; gets $f header
while {[gets $f line]>=0} {
 lassign [split $line \t] id name ref hierarchy
 if {[regexp {^(URAM|RAMB|DSP48)} $ref]} {set ids($name) $id; set refs($name) $ref}
}
close $f
open_checkpoint $dcp
# DSP48E2 is an expanded macro: its arcs live on DSP_* child primitives.
array set children {}
set dsps [get_cells -quiet -hier -filter {REF_NAME =~ DSP_*}]
foreach c $dsps name [vals NAME $dsps] {
 set ancestor [file dirname $name]
 while {$ancestor ne "." && $ancestor ne "/"} {
  if {[info exists ids($ancestor)]} {lappend children($ancestor) $c; break}
  set ancestor [file dirname $ancestor]
 }
}
set f [open $out/arcs.tsv w]; puts $f "cell_id\tkind\tfrom_pin\tto_pin"
set raw_arcs [open $out/raw_timing.tsv w];puts $raw_arcs "cell_id\tarc"
set pinfile [open $out/pins.tsv w];puts $pinfile "cell_id\tpin\tdirection\tclock"
set inv [open $out/macros.tsv w]; puts $inv "cell_id\tcell_name\tprimitive\tchildren\tactive_arcs\tdisabled_arcs\twires"
set count 0
foreach name [lsort [array names ids]] {
 set c [get_cells -quiet [list $name]]
 if {[llength $c]!=1 || [get_property NAME $c] ne $name || [get_property REF_NAME $c] ne $refs($name)} {error "Macro identity mismatch: $name"}
 set inside [list $c]
 if {[info exists children($name)]} {set inside [concat $inside $children($name)]}
 set prefixlen [expr {[string length $name]+1}]
 set pins [get_pins -quiet -of_objects $inside]
 set dirs [dict create]; set clocks [dict create]; set relative [dict create]
 set groups [dict create]
 foreach pin $pins pn [vals NAME $pins] dir [vals DIRECTION $pins] clk [vals IS_CLOCK $pins] conn [vals IS_CONNECTED $pins] {
  set rel [string range $pn $prefixlen end]
  puts $pinfile "$ids($name)\t$rel\t$dir\t$clk"
  if {$clk || !$conn} {continue}
  # Exposed macro inputs drive its interior; exposed outputs receive from it.
  set external [expr {[string first / $rel]<0}]
  if {[llength $inside]==1} {continue}
  set role $dir
  if {$external} {set role [dict get {IN OUT OUT IN} $dir]}
  set side upper
  if {$external} {set side lower}
  set net [get_nets -quiet -boundary_type $side -of_objects $pin]
  if {[llength $net]!=1} {error "Ambiguous macro net: $pn"}
  if {[get_property TYPE $net] in {POWER GROUND CLOCK}} {continue}
  set nn [get_property NAME $net]
  if {[string range $nn 0 [expr {$prefixlen-1}]] ne "$name/"} {error "Macro-local segment escaped: $nn"}
  dict lappend groups $nn [list $role $rel]
 }
 set wires 0
 dict for {net entries} $groups {
  set drivers {};set sinks {}
  foreach entry $entries {lassign $entry dir p; if {$dir eq "OUT"} {lappend drivers $p} else {lappend sinks $p}}
  # Tied external inputs are aliases of the same source; all are retained.
  foreach a $drivers {foreach b $sinks {
   if {$a eq $b} {continue}
   puts $f "$ids($name)\twire\t$a\t$b"; incr wires
  }}
 }
 set arcs [get_timing_arcs -quiet -of_objects $inside]
 set total [llength $arcs]
 set arcs [get_timing_arcs -quiet -of_objects $inside -filter {IS_DISABLED == 0}]
 set active [llength $arcs];set disabled [expr {$total-$active}]
 # Serialize the native collection in bulk. Python classifies these exact arcs.
 set names [get_property NAME $arcs]
 set lines [string map [list "$name/" ""] [join $names "\n$ids($name)\t"]]
 puts $raw_arcs "$ids($name)\t$lines"
 if {!$active} {error "No active timing arcs for macro $name"}
 puts $inv "$ids($name)\t$name\t$refs($name)\t[expr {[llength $inside]-1}]\t$active\t$disabled\t$wires"
 incr count
 if {$count%10==0} {say "macros=$count/[array size ids]";flush $f;flush $inv}
}
close $f;close $inv;close $raw_arcs;close $pinfile
set f [open $out/complete.txt w];puts $f "macros=$count";close $f
say "complete macros=$count"
close_design
exit

}
macro_main $argv
