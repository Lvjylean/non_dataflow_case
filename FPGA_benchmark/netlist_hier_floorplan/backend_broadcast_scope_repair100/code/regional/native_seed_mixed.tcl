# Small physical fixture for native API and full entry-point verification.
if {[catch {
set out [lindex $argv 0]
file mkdir $out
cd $out
set f [open fixture.v w]
puts $f {module fixture(input clk, input x, output [47:0] q);
wire broadcast;
(* DONT_TOUCH = "yes" *) FDRE source_reg(.C(clk), .CE(1'b1), .R(1'b0), .D(x), .Q(broadcast));
genvar i;
generate for(i=0;i<24;i=i+1) begin: bank
wire local_d;
(* DONT_TOUCH = "yes" *) LUT1 #(.INIT(2'h2)) distribution(.I0(broadcast), .O(local_d));
(* DONT_TOUCH = "yes" *) FDRE sink(.C(clk), .CE(1'b1), .R(1'b0), .D(local_d), .Q(q[i]));
end endgenerate
wire upstream_q, legacy_broadcast;
(* DONT_TOUCH = "yes" *) FDRE upstream_reg(.C(clk), .CE(1'b1), .R(1'b0), .D(x), .Q(upstream_q));
(* DONT_TOUCH = "yes" *) FDRE legacy_source_reg(.C(clk), .CE(1'b1), .R(1'b0), .D(upstream_q), .Q(legacy_broadcast));
generate for(i=0;i<24;i=i+1) begin: oldbank
wire local_d;
(* DONT_TOUCH = "yes" *) LUT1 #(.INIT(2'h2)) distribution(.I0(legacy_broadcast), .O(local_d));
(* DONT_TOUCH = "yes" *) FDRE sink(.C(clk), .CE(1'b1), .R(1'b0), .D(local_d), .Q(q[24+i]));
end endgenerate
endmodule}
close $f
create_project -in_memory -part xcu250-figd2104-2L-e
read_verilog fixture.v
synth_design -top fixture -mode out_of_context -no_iobuf
create_clock -period 10 [get_ports clk]
set source_sites [get_sites -of_objects [get_clock_regions X3Y9] -filter {SITE_TYPE =~ SLICE*}]
set source_site [lindex [lsort [get_property NAME $source_sites]] 0]
set_property LOC $source_site [get_cells source_reg]
set_property BEL AFF [get_cells source_reg]
for {set i 0} {$i < 24} {incr i} {
    set cr [lindex {X0Y7 X2Y7 X4Y6 X6Y10} [expr {$i/6}]]
    set sites [lsort [get_property NAME [get_sites -of_objects [get_clock_regions $cr] -filter {SITE_TYPE =~ SLICE*}]]]
    set site [lindex $sites [expr {10+$i%6}]]
    set lut [get_cells [list bank\[$i\].distribution]]
    set ff [get_cells [list bank\[$i\].sink]]
    set_property LOC $site $lut
    set_property BEL A6LUT $lut
    set_property LOC $site $ff
    set_property BEL AFF $ff
}
set source_sites [lsort [get_property NAME $source_sites]]
set_property LOC [lindex $source_sites 3] [get_cells legacy_source_reg]
set_property BEL AFF [get_cells legacy_source_reg]
set_property LOC [lindex $source_sites 4] [get_cells upstream_reg]
set_property BEL AFF [get_cells upstream_reg]
for {set i 0} {$i < 24} {incr i} {
    set cr [lindex {X0Y7 X2Y7 X4Y6 X6Y10} [expr {$i/6}]]
    set sites [lsort [get_property NAME [get_sites -of_objects [get_clock_regions $cr] -filter {SITE_TYPE =~ SLICE*}]]]
    set site [lindex $sites [expr {30+$i%6}]]
    set lut [get_cells [list oldbank\[$i\].distribution]]
    set ff [get_cells [list oldbank\[$i\].sink]]
    set_property LOC $site $lut
    set_property BEL A6LUT $lut
    set_property LOC $site $ff
    set_property BEL AFF $ff
}
place_design -no_psip -no_bufg_opt
write_checkpoint base.dcp
report_timing_summary -file baseline_timing.rpt
puts NATIVE_SEED_PASS
close_design
exit
} message options]} {
puts stderr [dict get $options -errorinfo]
exit 1
}
