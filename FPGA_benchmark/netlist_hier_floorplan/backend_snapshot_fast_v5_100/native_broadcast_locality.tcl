# Native regression only: 10 ns is deliberately generous for this tiny fixture.
# Run in two separate Vivado invocations:
#   -source native_broadcast_locality.tcl -tclargs CODE OUT run
#   -source native_broadcast_locality.tcl -tclargs CODE OUT reopen
# This exercises real discovery/ECO/STA/legalization/route code, not a mock plan.
if {[catch {
lassign $argv code out mode checkpoint
if {$mode eq ""} {set mode run}
if {$mode ni {run resume reopen}} {error "Expected run, resume or reopen"}
set ::env(BL_LOCALITY) 1
set ::env(JI_WNS_POLICY) positive
file mkdir $out
source $code/checkpoint_io.tcl
source $code/physical_eco.tcl
source $code/code/regional/core.tcl
source $code/code/regional/regional.tcl
source $code/code/regional/local_broadcast.tcl
lb::install
execopt::configure fast
set_param general.maxThreads 8

namespace eval fixture {}
# Match the production failure: edits detach leaves of an identity tree, so its
# old intermediate nets must be unlocked even when no replica directly reads or
# copies those drivers.  The fresh fixture also uses real hierarchical aliases.
proc fixture::inject_tree_protection {out require_aliases} {
    set saved {};set tree_nodes 0;set alias_groups 0
    foreach cell [get_cells -quiet -hier -filter {IS_PRIMITIVE == 1 && REF_NAME == LUT1}] {
        set name [get_property NAME $cell]
        if {![regexp {^tree\[[0-9]+\].*[/.]level[12]$} $name]} {continue}
        incr tree_nodes
        set pin [get_pins -quiet -of_objects $cell -filter {DIRECTION == OUT}]
        set nets [get_nets -quiet -segments -of_objects $pin]
        sb::require [expr {[llength $nets]>0}] "Identity tree output has no net: $name"
        if {[llength $nets]>1} {incr alias_groups}
        set_property DONT_TOUCH true $nets
        foreach net $nets {dict set saved [get_property NAME $net] [get_property DONT_TOUCH $net]}
    }
    sb::require [expr {$tree_nodes==8}] "Expected eight identity tree nodes, found $tree_nodes"
    if {$require_aliases} {
        sb::require [expr {$alias_groups>=4}] "Fresh fixture must expose at least four real hierarchical alias groups"
    }
    set f [open $out/protection_fixture.tcl w]
    puts $f [list set fixture_saved_protection $saved]
    puts $f [list set fixture_require_aliases $require_aliases]
    close $f
    set f [open $out/protection_injection.tsv w]
    puts $f "tree_nodes\tprotected_segments\thierarchy_alias_groups\trequire_aliases"
    puts $f "$tree_nodes\t[dict size $saved]\t$alias_groups\t$require_aliases"
    close $f
    return $saved
}
proc fixture::assert_legacy_gap {plan out require_aliases} {
    set local [dict get $plan local_broadcast]
    set snapshot [dict get $local snapshot];set graph [dict get $local graph]
    # Reconstruct the old (buggy) unlock selection without executing it.  This
    # keeps the regression meaningful after production unlock code is fixed.
    set touched {};set legacy {}
    dict for {name item} [dict get $graph replicas] {
        set key [dict get $item key];dict set touched $key 1
        dict for {pin sig} [dict get $snapshot roots $key inputs] {dict set touched [dict get $sig key] 1}
    }
    foreach key [dict keys $touched] {
        set net [dict get $snapshot nets $key]
        if {[dict get $net kind] eq "ordinary"} {
            set objects [get_nets -quiet -segments [lb::source_net $local $key]]
        } else {set objects [get_nets -quiet -of_objects [sb::pin [dict get $net anchor]]]}
        foreach obj $objects {dict set legacy [get_property NAME $obj] 1}
    }
    set missing {};set alias_missing {};set moved_sinks 0
    set f [open $out/protected_old_segment_coverage.tsv w]
    puts $f "sink\told_driver\tsegment\tprotected\tin_legacy_unlock\tgroup_segments"
    dict for {sink route} [dict get $graph moves] {
        lassign $route old target
        set segments [get_nets -quiet -segments -of_objects [sb::pin $sink]]
        foreach net $segments {
            set name [get_property NAME $net]
            set protected [sb::one_bit [get_property DONT_TOUCH $net]]
            set present [dict exists $legacy $name]
            puts $f "$sink\t$old\t$name\t$protected\t$present\t[llength $segments]"
            if {$protected && !$present} {
                dict set missing $name 1
                if {[llength $segments]>1} {dict set alias_missing $name 1}
            }
        }
        incr moved_sinks
    }
    close $f
    sb::require [expr {[dict size $missing]>0}] "Fixture does not reproduce protected old segments absent from legacy unlock"
    if {$require_aliases} {
        sb::require [expr {[dict size $alias_missing]>0}] "Fixture does not reproduce omitted protected hierarchical aliases"
    }
    set f [open $out/protected_old_segment_fixture_PASS w]
    puts $f "PASS moved_sinks=$moved_sinks omitted_protected_segments=[dict size $missing] omitted_hierarchical_segments=[dict size $alias_missing] require_aliases=$require_aliases"
    close $f
}
proc fixture::assert_tree_protection {saved folder} {
    file mkdir $folder
    set f [open $folder/protected_tree_properties.tsv w]
    puts $f "segment\texpected\tactual\tstatus"
    dict for {name expected} $saved {
        set object [get_nets -quiet [list $name]]
        sb::require [expr {[llength $object]==1}] "Protected original tree segment disappeared: $name"
        set actual [get_property DONT_TOUCH $object]
        sb::require [expr {$actual eq $expected}] "Original tree segment protection was not restored: $name expected=$expected actual=$actual"
        puts $f "$name\t$expected\t$actual\tPASS"
    }
    close $f
    set f [open $folder/protected_tree_PASS w]
    puts $f "PASS protected_segments=[dict size $saved] exact_properties_restored=1"
    close $f
}
proc fixture::signal {pin} {return [sb::signal $pin]}
proc fixture::assert_original_slrs {} {
    sb::spatial_cache
    foreach name {broadcast_ff ping_source data_source ce_source} {
        sb::require [expr {[dict get [sb::position $name] slr] eq "SLR1"}] "Original source SLR changed: $name"
    }
    foreach name {ping_a ping_b ping_shared} {
        sb::require [expr {[dict get [sb::position $name] slr] eq "SLR0"}] "Original shared cone SLR changed: $name"
    }
    sb::require [expr {[dict get [sb::position ping_end] slr] eq "SLR1"}] "Ping-pong endpoint drifted"
}
proc fixture::fanout {folder} {
    file mkdir $folder
    set f [open $folder/fanout.tsv w];puts $f "driver\tfanout"
    set maximum 0;set checked 0
    set roots [lsort -unique [sb::names [get_nets -quiet -segments -top_net_of_hierarchical_group \
        [get_nets -quiet -hier -filter {TYPE != POWER && TYPE != GROUND}]]]]
    foreach root $roots {
        set net [get_nets -quiet [list $root]]
        if {[llength [get_clocks -quiet -of_objects $net]]} {continue}
        set segs [get_nets -segments $net]
        set drivers [sb::names [get_pins -quiet -of_objects $segs -filter {IS_LEAF == 1 && DIRECTION == OUT}]]
        if {[llength $drivers]!=1} {continue}
        set driver [lindex $drivers 0]
        if {[get_property REF_NAME [get_cells -of_objects [get_pins [list $driver]]]] in {BUFG BUFGCE}} {continue}
        set sinks [sb::names [get_pins -quiet -of_objects $segs -filter {IS_LEAF == 1 && DIRECTION == IN && IS_CLOCK == 0}]]
        set fo [llength [lsort -unique $sinks]]
        sb::require [expr {$fo<100}] "Fixture ordinary fanout is not below 100: $driver ($fo)"
        set maximum [expr {max($maximum,$fo)}];incr checked
        puts $f "$driver\t$fo"
    }
    close $f
    set f [open $folder/fanout_PASS w];puts $f "ordinary_ge100=0 maximum=$maximum checked=$checked";close $f
}
proc fixture::assert_plan {plan} {
    set local [dict get $plan local_broadcast]
    sb::require [dict exists $local copies broadcast_ff/Q SLR0] "Hidden FF was not selected for its remote effective loads"
    set cone 0
    dict for {name item} [dict get $local graph replicas] {
        if {[dict get $item key] in {ping_a/O ping_b/O} && [dict get $item slr] eq "SLR1"} {incr cone}
    }
    sb::require [expr {$cone>=2}] "Both remote ping-pong LUT levels must be cloned together"
    return [dict get $local copies broadcast_ff/Q SLR0]
}
proc fixture::assert_input_proof {plan folder} {
    file mkdir $folder
    set copy [assert_plan $plan]
    set f [open $folder/input_proof.tsv w];puts $f "pin\toriginal_signal\tcopy_signal\tstatus"
    foreach pin {C D CE R} {
        set original [signal broadcast_ff/$pin]
        set observed [signal $copy/$pin]
        sb::require [expr {$original eq $observed}] "Fixture FF functional input changed: $pin"
        puts $f "$pin\t$original\t$observed\tPASS"
    }
    # The shared SLR0 branch must retain its old functional driver.
    set expected [list drivers [list ping_b/O]]
    sb::require [expr {[signal ping_shared/D] eq $expected}] "Original shared cone branch was stolen"
    sb::require [expr {[signal ping_end/D] ne $expected}] "Local cone endpoint was not rewired"
    close $f
    set f [open $folder/input_proof_PASS w];puts $f PASS;close $f
}

if {$mode eq "reopen"} {
    open_checkpoint $out/post_route.dcp
    source $out/plan.tcl
    source $out/protection_fixture.tcl
    sb::verify $sb_plan $out/reopened 1
    fixture::assert_original_slrs
    fixture::assert_input_proof $sb_plan $out/reopened
    fixture::fanout $out/reopened
    fixture::assert_tree_protection $fixture_saved_protection $out/reopened
    plg::assert_routed $out/reopened/physical
    report_timing_summary -delay_type min_max -file $out/reopened/timing_summary.rpt
    set f [open $out/REOPEN_PASS w];puts $f "PASS independent reopen: structure, hidden broadcast, complete shared cone, input proof, restored protected hierarchy segments, fanout and route";close $f
    close_design;exit
}

sb::require [expr {![file exists $out/post_route.dcp] && ![file exists $out/before.dcp]}] "Refusing to overwrite a previous fixture run"
if {$mode eq "resume"} {
    open_checkpoint $checkpoint
} else {
set f [open $out/fixture.v w]
puts $f {module fixture_tree(input state, output first, output second);
(* DONT_TOUCH="yes" *) LUT1 #(.INIT(2'h2)) level1(.I0(state),.O(first));
(* DONT_TOUCH="yes" *) LUT1 #(.INIT(2'h2)) level2(.I0(first),.O(second));
endmodule
module fixture(input clk, input [1:0] d, output [127:0] q, output local_q, output shared_q);
wire c; BUFG cg(.I(clk),.O(c));
wire data, ce, state, ps;
(* DONT_TOUCH="yes" *) FDRE data_source(.C(c),.CE(1'b1),.R(1'b0),.D(d[0]),.Q(data));
(* DONT_TOUCH="yes" *) FDRE ce_source(.C(c),.CE(1'b1),.R(1'b0),.D(d[1]),.Q(ce));
(* DONT_TOUCH="yes" *) FDRE broadcast_ff(.C(c),.CE(ce),.R(1'b0),.D(data),.Q(state));
(* DONT_TOUCH="yes" *) FDRE ping_source(.C(c),.CE(ce),.R(1'b0),.D(data),.Q(ps));
wire [3:0] first, second;
genvar k;
generate for(k=0;k<4;k=k+1) begin: tree
(* KEEP_HIERARCHY="yes" *) fixture_tree branch(.state(state),.first(first[k]),.second(second[k]));
end endgenerate
generate for(k=0;k<128;k=k+1) begin: sinks
wire v;
(* DONT_TOUCH="yes" *) FDRE r(.C(c),.CE(1'b1),.R(1'b0),.D(second[k/32]),.Q(v));
// The observer keeps the FF output internal, so the FF input is editable.
(* DONT_TOUCH="yes" *) LUT1 #(.INIT(2'h2)) observer(.I0(v),.O(q[k]));
end endgenerate
wire pa,pb,pe,shared;
(* DONT_TOUCH="yes" *) LUT2 #(.INIT(4'h8)) ping_a(.I0(ps),.I1(ce),.O(pa));
(* DONT_TOUCH="yes" *) LUT6 #(.INIT(64'h6996966996696996)) ping_b(.I0(pa),.I1(data),.I2(ce),.I3(ps),.I4(1'b1),.I5(1'b0),.O(pb));
(* DONT_TOUCH="yes" *) FDRE ping_end(.C(c),.CE(1'b1),.R(1'b0),.D(pb),.Q(pe));
(* DONT_TOUCH="yes" *) FDRE ping_shared(.C(c),.CE(1'b1),.R(1'b0),.D(pb),.Q(shared));
(* DONT_TOUCH="yes" *) LUT1 #(.INIT(2'h2)) ping_observer(.I0(pe),.O(local_q));
(* DONT_TOUCH="yes" *) LUT1 #(.INIT(2'h2)) shared_observer(.I0(shared),.O(shared_q));
endmodule}
close $f
create_project -in_memory -part xcu250-figd2104-2L-e
read_verilog $out/fixture.v
synth_design -top fixture -mode out_of_context -no_iobuf -flatten_hierarchy none
create_clock -period 10 [get_ports clk]
set_input_delay -clock [get_clocks clk] -max 3.2 [get_ports d*]
set_input_delay -clock [get_clocks clk] -min 3.0 [get_ports d*]
set_output_delay -clock [get_clocks clk] -max .2 [get_ports {q* local_q shared_q}]
set_output_delay -clock [get_clocks clk] -min .1 [get_ports {q* local_q shared_q}]
opt_design
foreach slr {SLR0 SLR1} {
    set pb [create_pblock original_$slr]
    resize_pblock $pb -add $slr
    set_property IS_SOFT false $pb
    set_property EXCLUDE_PLACEMENT false $pb
}
foreach obj [get_cells -hier -filter {IS_PRIMITIVE == 1}] {
    set name [get_property NAME $obj];set ref [get_property REF_NAME $obj]
    if {![regexp {^(FDRE|LUT[1-6])$} $ref]} {continue}
    set target SLR1
    if {$name in {ping_a ping_b ping_shared shared_observer}} {set target SLR0}
    if {[regexp {^sinks\[([0-9]+)\][/.]} $name unused index] && $index<112} {set target SLR0}
    add_cells_to_pblock [get_pblocks original_$target] $obj
}
place_design -no_psip -no_bufg_opt
write_checkpoint $out/before.dcp
}
fixture::assert_original_slrs
sb::require [expr {[llength [sb::loads broadcast_ff/Q]]==4}] "Fixture must hide its broadcast behind exactly four direct loads"
set remote 0;set local 0
foreach obj [get_cells -hier -filter {REF_NAME == FDRE}] {
    set name [get_property NAME $obj]
    if {![regexp {^sinks\[[0-9]+\][/.]r$} $name]} {continue}
    set slr [dict get [sb::position $name] slr]
    if {$slr eq "SLR0"} {incr remote} elseif {$slr eq "SLR1"} {incr local}
}
sb::require [expr {$remote==112 && $local==16}] "Fixture requires 112 remote plus 16 local effective terminals, got remote=$remote local=$local"

set fixture_require_aliases [expr {$mode eq "run"}]
set fixture_saved_protection [fixture::inject_tree_protection $out $fixture_require_aliases]
set plan [sb::scan $out 1000 16]
fixture::assert_plan $plan
fixture::assert_legacy_gap $plan $out $fixture_require_aliases
set plan [ji::capture_guard $plan $out]
set physical [plg::capture [dict keys [dict get $plan local_broadcast graph moves]] $out/physical_edit]
set plan [sb::apply $plan $out]
plg::release $physical
sb::verify $plan $out/after_edit 0
fixture::assert_input_proof $plan $out/after_edit
fixture::assert_tree_protection $fixture_saved_protection $out/after_edit
plg::place $out/physical_place -no_psip -no_bufg_opt
update_clock_routing
sb::verify $plan $out/post_place 1
fixture::assert_original_slrs
fixture::assert_input_proof $plan $out/post_place
fixture::fanout $out/post_place
fixture::assert_tree_protection $fixture_saved_protection $out/post_place
ji::placed_guard $plan $out
plg::before_route $out/pre_route
route_design
sb::verify $plan $out/post_route 1
fixture::assert_original_slrs
fixture::assert_input_proof $plan $out/post_route
fixture::fanout $out/post_route
fixture::assert_tree_protection $fixture_saved_protection $out/post_route
plg::assert_routed $out/physical_final
report_timing_summary -delay_type min_max -file $out/post_route/timing_summary.rpt
write_checkpoint $out/post_route.dcp
sb::save $plan $out/plan.tcl
set f [open $out/PASS w];puts $f "PASS hidden FF/direct4/effective128, remote112 cap, shared full cone, protected old hierarchy segments restored, exact inputs, placement, route; independent reopen still required";close $f
close_design;exit
} message options]} {
    puts stderr [dict get $options -errorinfo]
    exit 1
}
