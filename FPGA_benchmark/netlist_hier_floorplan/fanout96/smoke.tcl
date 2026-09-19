lassign $argv code output
file mkdir $output
cd $output
create_project -in_memory -part xcu250-figd2104-2L-e
set f [open shell.v w]; puts $f {module shell(input clk, output y); assign y=clk; endmodule}; close $f
read_verilog shell.v
synth_design -top shell -mode out_of_context -no_iobuf
create_clock -period 10 [get_ports clk]
source $code/core.tcl
set f96::target 3
proc broadcast {name ref out count {pin D}} {
    if {![llength [get_cells -quiet $name]]} {create_cell -reference $ref $name}
    set nn n_[string map {[ _ ] _} ${name}_${out}]
    create_net $nn
    connect_net -net [get_nets $nn] -objects [get_pins [list $name/$out]]
    for {set i 0} {$i < $count} {incr i} {
        set sink ${nn}_load_$i; create_cell -reference FDRE $sink
        connect_net -net [get_nets $nn] -objects [get_pins $sink/$pin]
        set f96::cr($sink) [expr {$i < 9 ? "X0Y4" : "X0Y8"}]
        set f96::slr($sink) [expr {$i < 9 ? "SLR1" : "SLR2"}]
    }
}
broadcast alpha FDRE Q 17
broadcast memory RAMB36E2 {DOUTADOUT[0]} 17
broadcast memory RAMB36E2 {DOUTADOUT[1]} 17
broadcast control_global BUFGCE O 17 CE
broadcast alpha_replica_1_replica_7 FDRE Q 17
broadcast sync_reset FDRE Q 17 R
broadcast true_clock FDRE Q 17 C
broadcast supply VCC P 17
create_port -direction IN external_enable
create_net external_control
connect_net -net [get_nets external_control] -objects [get_ports external_enable]
for {set i 0} {$i < 17} {incr i} {
    create_cell -reference FDRE input_load_$i
    connect_net -net [get_nets external_control] -objects [get_pins input_load_$i/CE]
}
# Old protected identity trees are flattened, then reconstructed exactly.
create_cell -reference LUT1 hfg_identity_0
set_property INIT 2'h2 [get_cells hfg_identity_0]
set old [f96::loads [get_pins alpha/Q]]
create_net hfg_identity_0_out
connect_net -net [get_nets hfg_identity_0_out] -objects [get_pins hfg_identity_0/O]
f96::disconnect $old
connect_net -net [get_nets hfg_identity_0_out] -objects $old
connect_net -net [get_nets n_alpha_Q] -objects [get_pins hfg_identity_0/I0]
set_property DONT_TOUCH true [get_cells hfg_identity_0]
set_property DONT_TOUCH true [get_nets hfg_identity_0_out]
f96::flatten_owned flatten
if {[f96::loads [get_pins alpha/Q]] ne $old} {error "Old tree flatten mismatch"}
set selected [f96::scan before 0]
if {[llength $selected] != 7} {error "Expected seven non-clock candidates: [llength $selected]"}
f96::apply $selected apply
foreach item $selected {if {[llength [f96::loads [dict get $item driver]]] > 3} {error "Root cap failed"}}
foreach item $selected {
    foreach flag [f96::values DONT_TOUCH [get_nets -segments -of_objects [dict get $item driver]]] {
        if {!$flag} {error "Repaired root is not protected"}
    }
}
foreach c [get_cells f96_identity_*] {
    if {[llength [f96::loads [get_pins $c/O]]] > 3} {error "Branch cap failed"}
    if {[get_property INIT $c] ne "2'h2"} {error "Helper INIT failed"}
}
if {[llength [f96::scan after 0]]} {error "Residual data/control fanout"}
# Exercise a second edit of an already protected tree, as required after a
# placer pass attaches new loads to an equivalent driver.
set growth_driver [get_pins alpha/Q]
set_property DONT_TOUCH false [get_nets -segments -of_objects $growth_driver]
for {set i 0} {$i < 7} {incr i} {
    create_cell -reference FDRE regrowth_load_$i
    connect_net -net [get_nets -of_objects $growth_driver] -objects [get_pins regrowth_load_$i/D]
}
set_property DONT_TOUCH true [get_nets -segments -of_objects $growth_driver]
set regrown [f96::scan regrown 0]
if {[llength $regrown] != 1} {error "Expected one regrown owned tree"}
f96::apply $regrown apply_regrowth
if {[llength [f96::scan after_regrowth 0]]} {error "Regrown tree cleanup failed"}
foreach flag [f96::values DONT_TOUCH [get_cells f96_identity_*]] {
    if {!$flag} {error "Owned helper protection was not restored"}
}
write_checkpoint patched.dcp
set count [llength [get_cells f96_identity_*]]
close_design
open_checkpoint patched.dcp
if {[llength [get_cells f96_identity_*]] != $count} {error "Reopen helper count"}
if {[llength [f96::scan reopened 0]]} {error "Reopened data/control fanout"}
foreach item $selected {
    set name [dict get $item driver_name]
    if {[dict get $item ref] eq ""} {set driver [get_ports [list $name]]} else {set driver [get_pins [list $name]]}
    if {[llength $driver] != 1} {error "Reopened driver name did not resolve"}
    foreach flag [f96::values DONT_TOUCH [get_nets -segments -of_objects $driver]] {
        if {!$flag} {error "Reopened repaired root is not protected"}
    }
}
set f [open PASS.txt w]
puts $f "PASS: independent BRAM bits, nested replica names, BUFG control included, synchronous reset, true clocks/constants excluded, spatial multi-level trees, old-tree flatten, exact sink coverage, root/branch caps and checkpoint reopen; helpers=$count"
close $f
puts F96_SMOKE_PASS
close_design
exit
