# A real two-SLR sequential/logic fixture, followed by a fresh-process readback.
if {[catch {
lassign $argv code out mode checkpoint
file mkdir $out
source $code/checkpoint_io.tcl
source $code/physical_eco.tcl
source $code/code/regional/core.tcl
source $code/code/regional/regional.tcl
source $code/code/regional/local_broadcast.tcl
lb::install
execopt::configure fast
set_param general.maxThreads 8
if {$mode eq "reopen"} {
    open_checkpoint $out/post_route.dcp
    source $out/plan.tcl
    sb::verify $sb_plan $out/reopened 1
    sb::reports $sb_plan $out/reopened 1
    plg::assert_routed $out/reopened/physical
    set f [open $out/REOPEN_PASS w]; puts $f PASS; close $f
    close_design
    exit
}
if {$mode eq "resume"} {
    open_checkpoint $checkpoint
} else {
set f [open $out/fixture.v w]
puts $f {module fixture(input clk,x,y,ce,rst,sel, output [127:0] q);
wire c,d,reset_q,enable_q,state_q,mux_q,set_q,broadcast;
BUFG cg(.I(clk),.O(c));
(* DONT_TOUCH="yes" *) FDRE rg(.C(c),.CE(1'b1),.R(1'b0),.D(rst),.Q(reset_q));
(* DONT_TOUCH="yes" *) FDRE eg(.C(c),.CE(1'b1),.R(1'b0),.D(ce),.Q(enable_q));
(* DONT_TOUCH="yes" *) LUT2 #(.INIT(4'h6)) d_logic(.I0(x),.I1(y),.O(d));
(* DONT_TOUCH="yes" *) FDRE #(.INIT(1'b1)) state(.C(c),.CE(enable_q),.R(reset_q),.D(d),.Q(state_q));
wire [3:0] md;wire [1:0] mf;wire mx;
genvar k;
generate for(k=0;k<4;k=k+1) begin: muxbank
(* DONT_TOUCH="yes" *) LUT6 #(.INIT(64'h6996966996696996)) ml(.I0(x),.I1(y),.I2(ce),.I3(rst),.I4(sel),.I5(state_q),.O(md[k]));
end endgenerate
(* DONT_TOUCH="yes" *) MUXF7 mf0(.I0(md[0]),.I1(md[1]),.S(sel),.O(mf[0]));
(* DONT_TOUCH="yes" *) MUXF7 mf1(.I0(md[2]),.I1(md[3]),.S(sel),.O(mf[1]));
(* DONT_TOUCH="yes" *) MUXF8 mux8(.I0(mf[0]),.I1(mf[1]),.S(x),.O(mx));
(* DONT_TOUCH="yes" *) FDRE mux_state(.C(c),.CE(enable_q),.R(reset_q),.D(mx),.Q(mux_q));
(* DONT_TOUCH="yes" *) FDSE #(.INIT(1'b0)) set_state(.C(c),.CE(enable_q),.S(reset_q),.D(d),.Q(set_q));
(* DONT_TOUCH="yes" *) LUT2 #(.INIT(4'h6)) data_logic(.I0(state_q),.I1(set_q),.O(broadcast));
generate for(k=0;k<32;k=k+1) begin: lane
wire h,l;
(* DONT_TOUCH="yes" *) LUT1 #(.INIT(2'h2)) helper(.I0(state_q),.O(h));
(* DONT_TOUCH="yes" *) LUT3 #(.INIT(8'h96)) consumer(.I0(h),.I1(x),.I2(y),.O(l));
(* DONT_TOUCH="yes" *) FDRE recv_a(.C(c),.CE(1'b1),.R(1'b0),.D(l),.Q(q[k]));
(* DONT_TOUCH="yes" *) FDRE recv_b(.C(c),.CE(1'b1),.R(1'b0),.D(mux_q),.Q(q[32+k]));
(* DONT_TOUCH="yes" *) FDRE recv_c(.C(c),.CE(set_q),.R(1'b0),.D(x),.Q(q[64+k]));
(* DONT_TOUCH="yes" *) FDRE recv_d(.C(c),.CE(1'b1),.R(1'b0),.D(broadcast),.Q(q[96+k]));
end endgenerate
endmodule}
close $f
create_project -in_memory -part xcu250-figd2104-2L-e
read_verilog $out/fixture.v
synth_design -top fixture -mode out_of_context -no_iobuf -flatten_hierarchy none
create_clock -period 6.7 [get_ports clk]
set_input_delay -clock [get_clocks clk] -max 0.2 [get_ports {x y ce rst sel}]
set_input_delay -clock [get_clocks clk] -min 0.1 [get_ports {x y ce rst sel}]
set_output_delay -clock [get_clocks clk] -max 0.2 [get_ports q*]
set_output_delay -clock [get_clocks clk] -min 0.1 [get_ports q*]
opt_design
foreach slr {SLR0 SLR1} {
    set pb [create_pblock fixture_$slr]; resize_pblock $pb -add $slr; set_property IS_SOFT false $pb
}
foreach cell [get_cells -hier -filter {IS_PRIMITIVE == 1}] {
    set name [get_property NAME $cell]; set ref [get_property REF_NAME $cell]
    if {![regexp {^(LUT|FD|MUXF)} $ref]} {continue}
    set target SLR0
    if {[regexp {lane\[([0-9]+)\]} $name unused i] && $i>=16} {set target SLR1}
    add_cells_to_pblock [get_pblocks fixture_$target] $cell
}
place_design -no_psip -no_bufg_opt
write_checkpoint $out/before.dcp
}
set plan [sb::scan $out 1000 16]
sb::require [expr {[dict get $plan ff_added]>=3 && [dict get $plan lut_added]>=1}] "Native fixture failed to exercise expanded FF/LUT rules"
set physical [plg::capture [dict keys [dict get $plan local_broadcast graph moves]] $out/physical_edit]
set plan [sb::apply $plan $out]
plg::release $physical
sb::verify $plan $out/after_edit 0
plg::place $out/physical_place -no_psip -no_bufg_opt
sb::verify $plan $out/post_place 1
plg::before_route $out/pre_route
route_design
sb::verify $plan $out/post_route 1
sb::reports $plan $out/post_route 1
write_checkpoint $out/post_route.dcp
plg::assert_routed $out/final_physical
sb::save $plan $out/plan.tcl
set f [open $out/PASS w]; puts $f "PASS native expanded FF/LUT replication, shared inputs, synchronous R/S, mobility, connectivity, placement and routing"; close $f
close_design
exit
} message options]} {puts stderr [dict get $options -errorinfo]; exit 1}
