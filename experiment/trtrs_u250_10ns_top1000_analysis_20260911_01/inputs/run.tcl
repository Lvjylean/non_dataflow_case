cd $::env(RUN_DIR)
set_param general.maxThreads 4
open_checkpoint $::env(INPUT_DCP)
if {[get_property PART [current_design]] ne "xcu250-figd2104-2L-e"} {error "Part mismatch"}
if {abs([get_property PERIOD [get_clocks ap_clk]]-10.0)>0.00001} {error "Clock mismatch"}
report_timing -delay_type max -sort_by slack -max_paths 1000 -nworst 1 -path_type full_clock_expanded -input_pins -file setup_paths_1000.rpt
# Resolve physical fanout for the bounded union of routed nets in these paths.
set f [open setup_paths_1000.rpt r]; set report [read $f]; close $f
set names [dict create]
foreach line [split $report \n] {
    if {[regexp {net \(fo=[0-9]+, routed\)\s+[-0-9.]+\s+[-0-9.]+\s+(.+)$} $line -> name]} {
        dict set names [string trim $name] 1
    }
}
set f [open path_net_fanout.tsv w]
puts $f "net\tdriver_pin\tdriver_ref\tlogical_loads_auxiliary\tphysical_site_pins\tclassification"
set unresolved 0
foreach name [lsort [dict keys $names]] {
    set net [get_nets -quiet $name]
    if {[llength $net] != 1 || [get_property NAME $net] ne $name} {
        puts $f "$name\tUNKNOWN\tUNKNOWN\tUNKNOWN\tUNKNOWN\tUNRESOLVED"
        incr unresolved; continue
    }
    set drivers [get_pins -quiet -leaf -of_objects $net -filter {DIRECTION == OUT}]
    set loads [get_pins -quiet -leaf -of_objects $net -filter {DIRECTION == IN}]
    set refs {}; foreach cell [get_cells -quiet -of_objects $drivers] {lappend refs [get_property REF_NAME $cell]}
    set class SIGNAL
    if {[llength [get_clocks -quiet -of_objects $net]]} {set class CLOCK}
    if {$refs eq "GND" || $refs eq "VCC"} {set class CONSTANT}
    set sitepins [lsort -unique [get_site_pins -quiet -of_objects $loads]]
    set physical [llength $sitepins]
    if {$physical == 0 && [llength $loads] > 0} {set physical UNKNOWN}
    puts $f "$name\t[join $drivers ,]\t[join $refs ,]\t[llength $loads]\t$physical\t$class"
    flush $f
}
close $f
set f [open analysis_complete.txt w]
puts $f "[clock format [clock seconds]] nets=[dict size $names] unresolved=$unresolved"
close $f
