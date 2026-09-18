# Extract native connectivity, including cells inside protected IP hierarchy.
set_param general.maxThreads 4
proc phase {s} {puts "COARSE_PHASE [clock seconds] $s"; flush stdout}
proc values {p objects} {
    if {![llength $objects]} {return {}}
    set v [get_property $p $objects]
    if {[llength $objects] == 1} {return [list $v]}
    return $v
}
set dcp [lindex $argv 0]
set raw [lindex $argv 1]
if {[file exists $raw/nets.tsv]} {error "Refusing to overwrite connectivity"}
array set ids {}; array set refs {}
set f [open $raw/cells.tsv r]; gets $f header
while {[gets $f line]>=0} {
    lassign [split $line \t] id name ref hierarchy
    set ids($name) $id; set refs($name) $ref
}
close $f
phase open
open_checkpoint $dcp
phase pins
set leaves [get_cells -quiet [array names ids]]
if {[llength $leaves] != [array size ids]} {error "Cell binding mismatch"}
set pins [get_pins -quiet -of_objects $leaves]
set expected 0
foreach clk [values IS_CLOCK $pins] connected [values IS_CONNECTED $pins] {
    if {$connected && !$clk} {incr expected}
}
phase nets
set nets [get_nets -quiet -segments -top_net_of_hierarchical_group -of_objects $pins]
unset pins
set ports [dict create]
foreach port [get_ports] {
    set pn [get_property NAME $port]
    set direction [dict get {IN OUT OUT IN INOUT INOUT} [get_property DIRECTION $port]]
    foreach n [get_nets -quiet -segments -top_net_of_hierarchical_group -of_objects $port] {
        dict lappend ports [get_property NAME $n] [list "PORT:$pn" $direction]
    }
}
set f [open $raw/nets.tsv w]
puts $f "net_id\ttype\tdrivers\tsinks"
array set seen {}
set count 0; set pin_count 0; set constants 0; set clock_pins 0
foreach net $nets nn [values NAME $nets] ty [values TYPE $nets] {
    if {[info exists seen($nn)]} {continue}
    set seen($nn) 1
    set segments [get_nets -quiet -segments $net]
    set pins [get_pins -quiet -of_objects $segments]
    set drivers [dict create]; set sinks [dict create]
    foreach p [values NAME $pins] dir [values DIRECTION $pins] clk [values IS_CLOCK $pins] {
        set slash [string last / $p]
        set cell [string range $p 0 [expr {$slash-1}]]
        if {![info exists ids($cell)]} {continue}
        if {$clk} {incr clock_pins; continue}
        incr pin_count
        set token "$ids($cell):[string range $p [expr {$slash+1}] end]"
        if {$dir eq "OUT"} {dict set drivers $token 1} elseif {$dir eq "IN"} {
            dict set sinks $token 1
        } else {error "Unsupported bidirectional primitive pin: $p"}
    }
    if {[dict exists $ports $nn]} {
        foreach entry [dict get $ports $nn] {
            lassign $entry token dir
            if {$dir eq "OUT"} {dict set drivers $token 1} elseif {$dir eq "IN"} {
                dict set sinks $token 1
            } else {error "Unsupported bidirectional port: $token"}
        }
    }
    puts $f "n$count\t$ty\t[join [dict keys $drivers] ,]\t[join [dict keys $sinks] ,]"
    incr count
    if {$count % 10000 == 0} {phase "nets=$count/[llength $nets] nonclock_pins=$pin_count"; flush $f}
}
close $f
if {$pin_count != $expected} {error "Connected pin total mismatch: $pin_count != $expected"}
set f [open $raw/connectivity_complete.txt w]
puts $f "nets=$count nonclock_pins=$pin_count clock_pins=$clock_pins"
close $f
phase complete
close_design
exit
