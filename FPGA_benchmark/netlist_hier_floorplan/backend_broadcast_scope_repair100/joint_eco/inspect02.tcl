# Read-only, cached cone inventory for the isolated GETRF joint timing ECO.
namespace eval jc {variable cells; variable edges; variable outputs; variable visiting; array set cells {}; array set edges {}; array set outputs {}; array set visiting {}}
proc jc::describe {name} {
    variable cells
    if {[info exists cells($name)]} {return $cells($name)}
    set c [sb::cell $name]; set ref [sb::ref $name]; set loc [get_property LOC $c]
    set slr {}; set cr {}; set x {}; set y {}; set init {}
    if {$loc ne {}} {
        set slr [dict get [sb::position $name] slr]
        set cr [get_property NAME [get_clock_regions -of_objects [get_sites [list $loc]]]]
        regexp {X([0-9]+)Y([0-9]+)} $cr unused x y
    }
    if {[regexp {^LUT[1-6]$} $ref]} {set init [string tolower [get_property INIT $c]]}
    set pbs [get_pblocks -quiet -of_objects $c]; set hard {}
    foreach pb $pbs {if {![sb::one_bit [get_property IS_SOFT $pb]]} {lappend hard [get_property NAME $pb]}}
    set cells($name) [dict create name $name ref $ref init $init slr $slr cr $cr x $x y $y loc $loc bel [get_property BEL $c] fixed [get_property IS_LOC_FIXED $c] hard [join $hard ,]]
    return $cells($name)
}
proc jc::expand {name depth seenvar} {
    variable edges; variable outputs; variable visiting
    upvar 1 $seenvar seen
    set data [describe $name]; set ref [dict get $data ref]
    if {![regexp {^(LUT[1-6]|MUXF[78])$} $ref]} {return}
    if {[dict exists $seen $name]} {return}
    if {$depth > 16 || [dict size $seen] >= 2048} {error "Cone bound exceeded: $name"}
    dict set seen $name 1
    if {![info exists edges($name)]} {
        set es {}
        foreach pin [sb::names [get_pins -of_objects [sb::cell $name] -filter {DIRECTION == IN && IS_LEAF == 1}]] {
            set sig [sb::signal $pin]
            if {[lindex $sig 0] eq "constant"} {
                lappend es [list $pin [lindex $sig 1] constant]
                continue
            }
            set ds [sb::drivers $pin]
            if {[llength $ds]!=1} {error "Unsupported multi-driver or port cone: $pin"}
            set d [lindex $ds 0]
            lappend es [list $pin $d driver]
            if {![info exists outputs($d)]} {set outputs($d) [sb::loads $d]}
        }
        set edges($name) $es
        set op "$name/O"
        set outputs($op) [sb::loads $op]
    }
    foreach edge $edges($name) {
        lassign $edge pin source kind
        if {$kind eq "driver"} {expand [file dirname $source] [expr {$depth+1}] seen}
    }
}
if {[catch {
lassign $argv flow input replicas out
file mkdir $out
source $flow/code/regional/core.tcl
set_param general.maxThreads 8
open_checkpoint $input
sb::require [expr {abs([get_property PERIOD [get_clocks ap_clk]]-6.7)<1e-6}] "Period mismatch"
sb::spatial_cache
set original_map {}
set f [open $replicas r]; gets $f
while {[gets $f line]>=0} {lassign [split $line \t] kind original replica slr loads; dict set original_map $replica $original}
close $f
set pf [open $out/paths.tsv w]; puts $pf "rank\tendpoint\tstartpoint\tslack\tcells"
set targets {}; set rank 0
foreach path [get_timing_paths -delay_type max -max_paths 1000 -nworst 1] {
    incr rank
    set ep [get_property ENDPOINT_PIN $path]; set c [file dirname $ep]
    set slack [get_property SLACK $path]
    set pcs {}
    puts $pf [join [list $rank $ep [get_property STARTPOINT_PIN $path] $slack [join $pcs |]] \t]
    if {$slack<0 && [file tail $ep] eq "D" && [sb::ref $c] in {FDRE FDSE}} {
        set original $c; if {[dict exists $original_map $c]} {set original [dict get $original_map $c]}
        lappend targets [dict create endpoint $ep original $original slack $slack]
    }
}
close $pf
set tf [open $out/targets.tsv w]; puts $tf "endpoint\toriginal\tslack\tdriver\tslr\tstatus\tcone_cells"
set guard {}
set i 0
foreach row $targets {
    incr i; dict with row {}
    set c [file dirname $endpoint]
    set ds [sb::drivers $endpoint]
    set seen {}; set why supported
    if {[llength $ds]!=1} {set why ambiguous} elseif {[catch {jc::expand [file dirname [lindex $ds 0]] 0 seen} reason]} {set why $reason}
    set pos [jc::describe $c]; jc::describe $original
    puts $tf [join [list $endpoint $original $slack [join $ds ,] [dict get $pos slr] $why [join [dict keys $seen] |]] \t]; flush $tf
    lappend guard [sb::pin "$original/D"] [sb::pin $endpoint]
    puts "CONE_INSPECT [clock seconds] $i/[llength $targets] cells=[array size jc::cells] cone=[dict size $seen] $why"; flush stdout
}
close $tf
set cf [open $out/cells.tsv w]; puts $cf "name\tref\tinit\tslr\tcr\tx\ty\tloc\tbel\tfixed\thard"
foreach name [lsort [array names jc::cells]] {set row $jc::cells($name); set vals {}; foreach key {name ref init slr cr x y loc bel fixed hard} {lappend vals [dict get $row $key]}; puts $cf [join $vals \t]}
close $cf
set ef [open $out/edges.tsv w]; puts $ef "sink\tsource\tkind"
foreach name [lsort [array names jc::edges]] {foreach edge $jc::edges($name) {puts $ef [join $edge \t]}}
close $ef
set of [open $out/loads.tsv w]; puts $of "driver\tsinks"
foreach pin [lsort [array names jc::outputs]] {puts $of "$pin\t[join $jc::outputs($pin) |]"}
close $of
set gf [open $out/guard.tsv w]; puts $gf "endpoint\ttype\tslack\tstartpoint"
foreach type {max min} {
    foreach p [get_timing_paths -to [lsort -unique $guard] -delay_type $type -max_paths 2000 -nworst 1] {puts $gf "[get_property ENDPOINT_PIN $p]\t$type\t[get_property SLACK $p]\t[get_property STARTPOINT_PIN $p]"}
}
close $gf
report_timing_summary -delay_type min_max -file $out/timing_summary.rpt
set f [open $out/PASS w]; puts $f "PASS read-only bounded cone inventory"; close $f
close_design
exit
} msg opts]} {puts stderr [dict get $opts -errorinfo]; if {[info exists out]} {set f [open $out/error.txt w]; puts $f [dict get $opts -errorinfo]; close $f}; exit 1}
