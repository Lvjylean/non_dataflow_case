# Isolated hierarchy probe. Never enable cross-segment batching from this alone.
if {[catch {
lassign $argv code out clock_port module_id
if {$clock_port eq ""} {set clock_port ap_clk}
if {$module_id eq ""} {set module_id S00}
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
puts $f [string map [list ap_clk $clock_port] {(* KEEP_HIERARCHY="yes" *) module leaf(input ap_clk,d,output q);
(* DONT_TOUCH="yes" *) FDRE receiver(.C(ap_clk),.CE(1'b1),.R(1'b0),.D(d),.Q(q));
endmodule
(* KEEP_HIERARCHY="yes" *) module tile(input ap_clk,d,output [127:0] q);
genvar i; generate for(i=0;i<128;i=i+1) begin: lane
(* KEEP_HIERARCHY="yes" *) leaf u(.ap_clk(ap_clk),.d(d),.q(q[i]));
end endgenerate endmodule
module fixture(input ap_clk,x,output [511:0] q,output other_q);
wire n;
(* DONT_TOUCH="yes" *) FDRE root(.C(ap_clk),.CE(1'b1),.R(1'b0),.D(x),.Q(n));
(* DONT_TOUCH="yes" *) FDRE other(.C(ap_clk),.CE(1'b1),.R(1'b0),.D(x),.Q(other_q));
genvar i; generate for(i=0;i<4;i=i+1) begin: bank
(* KEEP_HIERARCHY="yes" *) tile u(.ap_clk(ap_clk),.d(n),.q(q[128*i+:128]));
end endgenerate endmodule}]
close $f
create_project -in_memory -part xcu250-figd2104-2L-e
set_param general.maxThreads 8
read_verilog $out/probe.v
synth_design -top fixture -mode out_of_context -no_iobuf -flatten_hierarchy none
create_clock -period 10 [get_ports [list $clock_port]]
set_property DONT_TOUCH false [get_cells -hier]
set_property DONT_TOUCH false [get_nets -hier]
opt_design
write_checkpoint $out/post_opt.dcp
file mkdir $out/inputs
set f [open $out/inputs/membership.tsv w]
puts $f "cell\tmodule\tresource\tref"
foreach cell [get_cells -hier -filter {IS_PRIMITIVE == 1}] {
    set ref [get_property REF_NAME $cell]
    puts $f "[get_property NAME $cell]\t$module_id\tFF\t$ref"
}
close $f
set f [open $out/inputs/regions.tcl w]
puts $f [list set planned_regions [dict create $module_id {X0Y4 X1Y4 X2Y4 X3Y4 X4Y4 X5Y4 X6Y4 X7Y4}]]
puts $f [list set planned_bounds [dict create $module_id {0 4 7 4}]]
close $f
# Also exercise the actual base tree implementation on a placed fixture.
place_design
write_checkpoint $out/placed.dcp
close_design
set f [open $out/PASS w]; puts $f PASS; close $f
exit
} message options]} {puts stderr [dict get $options -errorinfo]; exit 1}
