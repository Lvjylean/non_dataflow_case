# Isolated hierarchy probe. Never enable cross-segment batching from this alone.
if {[catch {
lassign $argv code out
file mkdir $out
source $code/code/regional/core.tcl
namespace eval f96 {}
proc f96::plain_names {objects} {return [sb::names $objects]}
source $code/boundary.tcl
proc graph_snapshot {} {
    set ::sb::signal_cache {}
    set result {}
    foreach pin [lsort [sb::names [get_pins -hier -filter {IS_LEAF == 1 && DIRECTION == IN}]]] {
        set nets [get_nets -quiet -of_objects [get_pins [list $pin]]]
        if {[llength $nets]} {set signal [sb::signal $pin]} else {set signal disconnected}
        lappend result [list $pin $signal]
    }
    return $result
}
set f [open $out/probe.v w]
puts $f {(* KEEP_HIERARCHY="yes" *) module leaf(input clk,d,output q);
(* DONT_TOUCH="yes" *) FDRE receiver(.C(clk),.CE(1'b1),.R(1'b0),.D(d),.Q(q));
endmodule
(* KEEP_HIERARCHY="yes" *) module tile(input clk,d,output [7:0] q);
genvar i; generate for(i=0;i<8;i=i+1) begin: lane
(* KEEP_HIERARCHY="yes" *) leaf u(.clk(clk),.d(d),.q(q[i]));
end endgenerate endmodule
module fixture(input clk,x,output [31:0] q,output other_q);
wire n;
(* DONT_TOUCH="yes" *) FDRE root(.C(clk),.CE(1'b1),.R(1'b0),.D(x),.Q(n));
(* DONT_TOUCH="yes" *) FDRE other(.C(clk),.CE(1'b1),.R(1'b0),.D(x),.Q(other_q));
genvar i; generate for(i=0;i<4;i=i+1) begin: bank
(* KEEP_HIERARCHY="yes" *) tile u(.clk(clk),.d(n),.q(q[8*i+:8]));
end endgenerate endmodule}
close $f
create_project -in_memory -part xcu250-figd2104-2L-e
set_param general.maxThreads 8
read_verilog $out/probe.v
synth_design -top fixture -mode out_of_context -no_iobuf -flatten_hierarchy none
create_clock -period 10 [get_ports clk]
set_property DONT_TOUCH false [get_cells -hier]
set_property DONT_TOUCH false [get_nets -hier]
set before [graph_snapshot]
set loads [sb::loads root/Q]
if {[llength $loads] != 32} {error "Fixture hierarchy disappeared"}
set selected {}
for {set i 0} {$i < [llength $loads]} {incr i 2} {lappend selected [lindex $loads $i]}
write_checkpoint $out/seed.dcp
close_design
set results [open $out/result.tsv w]
puts $results "case\tmode\tboundaries\tleaves\tterminals\tcalls\telapsed_us"
foreach case {uniform mixed} {
    set reference {}
    foreach mode {reference boundary} {
        open_checkpoint $out/seed.dcp
        set groups {}; set g0 {}; set g1 {}
        foreach pin [lsort [sb::loads root/Q]] {
            if {$case eq "uniform"} {set which [expr {[string first {bank[0]} $pin] == 0 || [string first {bank[1]} $pin] == 0}]
            } else {set which [regexp {lane\[[0246]\]} $pin]}
            if {$which} {lappend g0 $pin} else {lappend g1 $pin}
        }
        set groups [list new0 $g0 new1 $g1]
        set plan [boundary::prepare root/Q $groups]
        set start [clock microseconds]; set calls 0
        if {$mode eq "reference"} {
            array set local {}
            foreach pin [concat $g0 $g1] {lappend local([get_property NAME [get_nets -of_objects [get_pins [list $pin]]]]) $pin}
            foreach net [array names local] {disconnect_net -net [get_nets [list $net]] -pinlist [get_pins $local($net)]; incr calls}
            array unset local *
            set pairs {}; foreach {net pins} $groups {foreach pin $pins {lappend pairs $net $pin}}
        } else {
            foreach {net pins} [dict get $plan disconnect] {disconnect_net -net [get_nets [list $net]] -pinlist [get_pins $pins]; incr calls}
            set pairs [dict get $plan pairs]
        }
        create_cell -reference LUT1 {helper0 helper1}
        set_property INIT 2'h2 [get_cells {helper0 helper1}]
        create_net {new0 new1}
        connect_net -hierarchical -net [get_nets -of_objects [get_pins root/Q]] -objects [get_pins {helper0/I0 helper1/I0}]
        connect_net -net [get_nets new0] -objects [get_pins helper0/O]
        connect_net -net [get_nets new1] -objects [get_pins helper1/O]
        set objects {}; foreach {net pin} $pairs {lappend objects [get_nets [list $net]] [get_pins [list $pin]]}
        connect_net -hierarchical -dict $objects
        set elapsed [expr {[clock microseconds]-$start}]
        foreach helper {helper0 helper1} pins [list $g0 $g1] {
            if {[lsort [sb::loads $helper/O]] ne [lsort $pins]} {error "Full leaf set mismatch for $case/$mode/$helper"}
        }
        set graph [graph_snapshot]
        if {$mode eq "reference"} {set reference $graph} elseif {$graph ne $reference} {error "Reference graph mismatch"}
        write_checkpoint $out/${case}_${mode}.dcp
        close_design
        open_checkpoint $out/${case}_${mode}.dcp
        if {[graph_snapshot] ne $graph} {error "Reopened graph mismatch"}
        close_design
        puts $results "$case\t$mode\t[dict get $plan boundaries]\t[dict get $plan leaves]\t[dict get $plan terminals]\t$calls\t$elapsed"
        flush $results
    }
}
close $results
set f [open $out/PASS w]; puts $f "PASS complete leaf graph and reopened graph"; close $f
exit
} message options]} {
puts stderr [dict get $options -errorinfo]
exit 1
}
