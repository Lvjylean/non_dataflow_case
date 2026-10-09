# Native regression: break a legal MUXF8/CFF packing, then legalize before routing.
if {[catch {
    lassign $argv code out mode
    file mkdir $out
    source $code/physical_eco.tcl
    set_param general.maxThreads 8
    if {$mode eq "reopen"} {
        open_checkpoint $out/post_route.dcp
        plg::assert_routed $out/reopened
        plg::require [expr {[get_property NAME [get_nets -of_objects [get_pins receiver/D]]] eq [get_property NAME [get_nets -of_objects [get_ports ext]]]}] "Reopened D connection changed"
        set f [open $out/REOPEN_PASS w]; puts $f PASS; close $f
        close_design; exit
    }
    set f [open $out/fixture.v w]
    puts $f {module fixture(input clk, input [23:0] x, input [2:0] s, input ce, input ext, output q, output old_mux);
wire c; BUFG cg(.I(clk),.O(c));
wire [3:0] d; wire [1:0] m;
(* DONT_TOUCH="yes" *) LUT6 #(.INIT(64'h6996966996696996)) ld(.I0(x[0]),.I1(x[1]),.I2(x[2]),.I3(x[3]),.I4(x[4]),.I5(x[5]),.O(d[0]));
(* DONT_TOUCH="yes" *) LUT6 #(.INIT(64'h6996966996696996)) lc(.I0(x[6]),.I1(x[7]),.I2(x[8]),.I3(x[9]),.I4(x[10]),.I5(x[11]),.O(d[1]));
(* DONT_TOUCH="yes" *) LUT6 #(.INIT(64'h6996966996696996)) lb(.I0(x[12]),.I1(x[13]),.I2(x[14]),.I3(x[15]),.I4(x[16]),.I5(x[17]),.O(d[2]));
(* DONT_TOUCH="yes" *) LUT6 #(.INIT(64'h6996966996696996)) la(.I0(x[18]),.I1(x[19]),.I2(x[20]),.I3(x[21]),.I4(x[22]),.I5(x[23]),.O(d[3]));
(* DONT_TOUCH="yes" *) MUXF7 mcd(.I0(d[0]),.I1(d[1]),.S(s[0]),.O(m[0]));
(* DONT_TOUCH="yes" *) MUXF7 mab(.I0(d[2]),.I1(d[3]),.S(s[1]),.O(m[1]));
(* DONT_TOUCH="yes" *) MUXF8 mux8(.I0(m[0]),.I1(m[1]),.S(s[2]),.O(old_mux));
(* DONT_TOUCH="yes" *) FDRE #(.INIT(1'b1)) receiver(.C(c),.CE(ce),.R(1'b0),.D(old_mux),.Q(q));
endmodule}
    close $f
    create_project -in_memory -part xcu250-figd2104-2L-e
    read_verilog $out/fixture.v
    synth_design -top fixture -mode out_of_context -no_iobuf -flatten_hierarchy none
    create_clock -period 6.7 [get_ports clk]
    opt_design
    foreach name {ld lc lb la mcd mab mux8 receiver} bel {D6LUT C6LUT B6LUT A6LUT F7MUX_CD F7MUX_AB F8MUX_BOT CFF} {
        set_property BEL $bel [get_cells $name]
        set_property LOC SLICE_X119Y294 [get_cells $name]
    }
    place_design -no_psip -no_bufg_opt
    set all [get_cells {ld lc lb la mcd mab mux8 receiver}]
    set_property IS_LOC_FIXED false $all
    set_property IS_BEL_FIXED false $all
    set before [plg::status $out/before]
    plg::require [expr {[dict get $before placement_errors] == 0}] "Fixture baseline is illegal"
    set original_ce [get_property NAME [get_nets -of_objects [get_pins receiver/CE]]]
    set original_init [get_property INIT [get_cells receiver]]
    set capture [plg::capture {receiver/D} $out/edit]
    set_property DONT_TOUCH false [get_cells receiver]
    set old [get_nets -of_objects [get_pins receiver/D]]
    set_property DONT_TOUCH false $old
    disconnect_net -net $old -pinlist [get_pins receiver/D]
    set extnet [get_nets -of_objects [get_ports ext]]
    if {![llength $extnet]} {
        create_net external_data
        set extnet [get_nets external_data]
        connect_net -net $extnet -objects [get_ports ext]
    }
    connect_net -net $extnet -objects [get_pins receiver/D]
    set_property DONT_TOUCH true [get_cells receiver]
    set broken [plg::status $out/broken]
    plg::require [expr {[dict get $broken placement_errors] > 0}] "Fixture did not reproduce changed-D packing failure"
    set blocked [catch {plg::before_route $out/rejected_gate} message]
    plg::require $blocked "Illegal placement was allowed to route"
    plg::release $capture
    plg::require [expr {[get_property LOC [get_cells receiver]] eq ""}] "Changed FF remained placed"
    plg::place $out/legalization -no_psip -no_bufg_opt
    plg::require [expr {[get_property NAME [get_nets -of_objects [get_pins receiver/D]]] eq [get_property NAME [get_nets -of_objects [get_ports ext]]]}] "New D was not retained"
    plg::require [expr {[get_property NAME [get_nets -of_objects [get_pins receiver/CE]]] eq $original_ce}] "CE changed"
    plg::require [expr {[get_property INIT [get_cells receiver]] eq $original_init}] "INIT changed"
    plg::require [expr {[get_property DONT_TOUCH [get_cells receiver]]}] "Function protection lost"
    plg::before_route $out/pre_route
    route_design
    write_checkpoint $out/post_route.dcp
    plg::assert_routed $out/final
    set f [open $out/PASS w]; puts $f "Illegal packing reproduced, blocked, legalized with new D retained, one full route passed"; close $f
    close_design; exit
} message options]} {puts stderr [dict get $options -errorinfo]; exit 1}
