# Native full MUX cone, FF copy, physical legalization and independent reopen.
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
if {[info exists ::env(JI_VALIDATE_FAST)] && $::env(JI_VALIDATE_FAST)} {
    rename jif::guard_slacks jif::guard_slacks_fast
    proc jif::guard_slacks {pins path} {
        ji::slacks_reference $pins ${path}.reference.tsv
        set actual [guard_slacks_fast $pins $path]
        exec python3 $::code/compare_timing_slacks.py ${path}.reference.tsv $path ${path}.comparison.json
        return $actual
    }
}
set_param general.maxThreads 8
if {$mode eq "reopen"} {
    open_checkpoint $out/post_route.dcp
    source $out/plan.tcl
    sb::verify $sb_plan $out/reopened 1
    plg::assert_routed $out/reopened/physical
    report_timing_summary -delay_type min_max -file $out/reopened/timing_summary.rpt
    set f [open $out/REOPEN_PASS w];puts $f PASS;close $f
    close_design;exit
}
if {$mode eq "resume"} {
    open_checkpoint $checkpoint
    # Valid external input min/max delays keep this fixture's hold checks meaningful.
    set_input_delay -clock [get_clocks clk] -max 3.2 [get_ports d*]
    set_input_delay -clock [get_clocks clk] -min 3.0 [get_ports d*]
} else {
set f [open $out/fixture.v w]
puts $f {module fixture(input clk, input [7:0] d, output [31:0] q);
wire c; BUFG cg(.I(clk),.O(c));
wire [7:0] src;
genvar i;
generate for(i=0;i<8;i=i+1) begin: sources
(* DONT_TOUCH="yes" *) FDRE r(.C(c),.CE(1'b1),.R(1'b0),.D(d[i]),.Q(src[i]));
end endgenerate
wire [3:0] a;wire [1:0] b;wire v,s;
generate for(i=0;i<4;i=i+1) begin: bank
(* DONT_TOUCH="yes" *) LUT6 #(.INIT(64'h6996966996696996)) l(.I0(src[0]),.I1(src[1]),.I2(src[2]),.I3(src[3]),.I4(src[4]),.I5(src[5]),.O(a[i]));
end endgenerate
(* DONT_TOUCH="yes" *) MUXF7 a0(.I0(a[0]),.I1(a[1]),.S(src[6]),.O(b[0]));
(* DONT_TOUCH="yes" *) MUXF7 a1(.I0(a[2]),.I1(a[3]),.S(src[6]),.O(b[1]));
(* DONT_TOUCH="yes" *) MUXF8 last(.I0(b[0]),.I1(b[1]),.S(src[7]),.O(v));
(* DONT_TOUCH="yes" *) FDRE state(.C(c),.CE(1'b1),.R(1'b0),.D(v),.Q(s));
generate for(i=0;i<32;i=i+1) begin: sinks
(* DONT_TOUCH="yes" *) FDRE r(.C(c),.CE(1'b1),.R(1'b0),.D(s),.Q(q[i]));
end endgenerate
endmodule}
close $f
create_project -in_memory -part xcu250-figd2104-2L-e
read_verilog $out/fixture.v
synth_design -top fixture -mode out_of_context -no_iobuf -flatten_hierarchy none
create_clock -period 10 [get_ports clk]
set_input_delay -clock [get_clocks clk] -max 3.2 [get_ports d*]
set_input_delay -clock [get_clocks clk] -min 3.0 [get_ports d*]
set_output_delay -clock [get_clocks clk] -max .2 [get_ports q*]
set_output_delay -clock [get_clocks clk] -min .1 [get_ports q*]
opt_design
foreach slr {SLR0 SLR1} {
    set pb [create_pblock original_$slr];resize_pblock $pb -add $slr;set_property IS_SOFT false $pb
}
foreach c [get_cells -hier -filter {IS_PRIMITIVE == 1}] {
    set name [get_property NAME $c];set ref [get_property REF_NAME $c]
    if {![regexp {^(LUT|FD|MUXF)} $ref]} {continue}
    set target SLR1
    if {[string match sources* $name] || ([regexp {sinks\[([0-9]+)\]} $name unused i] && $i<16)} {set target SLR0}
    add_cells_to_pblock [get_pblocks original_$target] $c
}
place_design -no_psip -no_bufg_opt
write_checkpoint $out/before.dcp
}
set plan [sb::scan $out 1000 16]
sb::require [expr {[dict get $plan ff_added]==1 && [dict get $plan lut_added]==4}] "Expected one FF and a complete four-LUT/MUX cone"
sb::require [expr {[dict size [dict get $plan local_broadcast graph replicas]]==8}] "Expected three complete MUX primitives"
set plan [ji::capture_guard $plan $out]
set physical [plg::capture [dict keys [dict get $plan local_broadcast graph moves]] $out/physical_edit]
set plan [sb::apply $plan $out]
plg::release $physical
sb::verify $plan $out/after_edit 0
plg::place $out/physical_place -no_psip -no_bufg_opt
update_clock_routing
sb::verify $plan $out/post_place 1
ji::placed_guard $plan $out
plg::before_route $out/pre_route
route_design
sb::verify $plan $out/post_route 1
plg::assert_routed $out/physical_final
report_timing_summary -delay_type min_max -file $out/post_route/timing_summary.rpt
write_checkpoint $out/post_route.dcp
sb::save $plan $out/plan.tcl
set f [open $out/PASS w];puts $f "PASS native complete-MUX/FF joint planning, exact connections, guards, legality and routing";close $f
close_design;exit
} message options]} {puts stderr [dict get $options -errorinfo];exit 1}
