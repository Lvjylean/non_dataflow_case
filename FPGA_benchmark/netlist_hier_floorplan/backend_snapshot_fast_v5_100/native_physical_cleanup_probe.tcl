# Three fresh Vivado processes: build, legacy, fast; never reuse a cleaned design.
# -tclargs CODE OUT MODE [BATCH_SIZE=32768]
# The fixture is intentionally small; it validates semantics, not full-design RAM.
namespace eval plg_probe {}
proc plg_probe::save_dict {path value} {set f [open $path w];puts $f $value;close $f}
proc plg_probe::read_dict {path} {set f [open $path];set value [read $f];close $f;return $value}
proc plg_probe::escaped {value} {return [string map [list "\t" {\t} "\r" {\r} "\n" {\n}] $value]}
proc plg_probe::hard_slr {name slr cell_names} {
    set regions [get_clock_regions -of_objects [get_slrs $slr]]
    plg::require [expr {[llength $regions] > 0}] "Probe SLR has no clock regions: $slr"
    create_pblock $name
    set pb [get_pblocks $name]
    foreach region [plg::names $regions] {resize_pblock $pb -add CLOCKREGION_${region}:CLOCKREGION_${region}}
    set_property IS_SOFT false $pb
    add_cells_to_pblock $pb [plg::exact cell $cell_names]
}
proc plg_probe::assert_slr {cell_names expected} {
    set objects [plg::exact cell $cell_names]
    foreach loc [plg::values LOC $objects] {
        plg::require [string match SLICE_* $loc] "Probe cell was not placed in a Slice: $loc"
    }
    set actual [lsort -unique [plg::names [get_slrs -of_objects [get_sites -of_objects $objects]]]]
    plg::require [expr {$actual eq [list $expected]}] "Probe cells escaped $expected: $actual"
}
proc plg_probe::ordinary_witnesses {source_pins path} {
    # Top-port nets can be implicitly routed in OOC mode. FF Q nets crossing
    # hard SLR regions must carry fabric routing before either cleanup runs.
    set objects [get_nets -of_objects [plg::exact pin $source_pins]]
    plg::require [expr {[llength $objects] == 64}] "Probe lost registered data nets"
    set f [open $path w];puts $f "net\tsource_slr\tsink_slr"
    foreach name [plg::names $objects] type [plg::values TYPE $objects] \
        status [plg::values ROUTE_STATUS $objects] route [plg::values ROUTE $objects] {
        plg::require [expr {$type eq "SIGNAL" && $status eq "ROUTED" && [string trim $route " \t\r\n{}"] ne ""}] \
            "Probe ordinary net has no complete fabric route: $name ($type/$status)"
        puts $f "$name\tSLR0\tSLR1"
    }
    close $f
    return [lsort -unique [plg::names $objects]]
}
proc plg_probe::route_state {path} {
    set all [get_nets -quiet -hierarchical]
    plg::require [expr {[llength $all] > 0}] "Probe has no live nets"
    set sample [plg::exact net [list [lindex [plg::names $all] 0]]]
    set properties [list_property $sample]
    foreach property {NAME TYPE ROUTE_STATUS ROUTE} {
        plg::require [expr {$property in $properties}] "Probe requires native net property $property"
    }
    set f [open $path w];puts $f "net\ttype\troute_status\troute"
    foreach batch [plg::batches [lsort -unique [plg::names $all]]] {
        set objects [plg::exact net $batch]
        foreach name [plg::names $objects] type [plg::values TYPE $objects] \
            status [plg::values ROUTE_STATUS $objects] route [plg::values ROUTE $objects] {
            set row {}
            foreach value [list $name $type $status $route] {lappend row [escaped $value]}
            puts $f [join $row \t]
        }
    }
    close $f
}
if {[catch {
    lassign $argv code out mode batch_size
    set code [file normalize $code];set out [file normalize $out]
    if {$mode ni {build legacy fast}} {error "Expected build/legacy/fast"}
    if {$batch_size eq ""} {set batch_size 32768}
    if {[file exists $out/$mode]} {error "Refusing to overwrite cleanup probe evidence"}
    file mkdir $out/$mode
    source $code/physical_eco.tcl
    source $code/physical_cleanup_reference.tcl
    set ::env(PLG_CLEANUP_BATCH_SIZE) $batch_size
    plg::cleanup_batch_size
    set_param general.maxThreads 8
    if {$mode eq "build"} {
        if {[file exists $out/baseline_edited.dcp]} {error "Refusing to overwrite probe checkpoint"}
        set f [open $out/build/fixture.v w]
        puts $f {module leaf(input clk, input [5:0] x, output q, output old);
(* DONT_TOUCH="yes" *) LUT6 #(.INIT(64'h6996966996696996)) logic_cell(.I0(x[0]),.I1(x[1]),.I2(x[2]),.I3(x[3]),.I4(x[4]),.I5(x[5]),.O(old));
(* DONT_TOUCH="yes" *) FDRE #(.INIT(1'b1)) receiver(.C(clk),.CE(1'b1),.R(1'b0),.D(old),.Q(q));
endmodule
module fixture(input clk, input [63:0] x, input ext, output [255:0] q, output [255:0] old);
wire c; wire [63:0] registered; BUFG clock_buffer(.I(clk),.O(c));}
        set source_names {};set source_pins {};set leaf_names {}
        for {set i 0} {$i < 64} {incr i} {
            puts $f [format {(* DONT_TOUCH="yes" *) FDRE #(.INIT(1'b0)) source_%d(.C(c),.CE(1'b1),.R(1'b0),.D(x[%d]),.Q(registered[%d]));} $i $i $i]
            lappend source_names source_$i
            lappend source_pins source_$i/Q
        }
        for {set i 0} {$i < 256} {incr i} {
            set inputs {}
            for {set j 0} {$j < 6} {incr j} {lappend inputs [format {registered[%d]} [expr {($i*7+$j)%64}]]}
            puts $f [format {(* KEEP_HIERARCHY="yes" *) leaf unit_%d(.clk(c),.x({%s}),.q(q[%d]),.old(old[%d]));} $i [join $inputs ,] $i $i]
            lappend leaf_names unit_$i/logic_cell unit_$i/receiver
        }
        puts $f {endmodule};close $f
        create_project -in_memory -part xcu250-figd2104-2L-e
        read_verilog $out/build/fixture.v
        synth_design -top fixture -mode out_of_context -no_iobuf -flatten_hierarchy none
        create_clock -period 6.7 [get_ports clk]
        opt_design
        plg_probe::hard_slr cleanup_sources SLR0 $source_names
        plg_probe::hard_slr cleanup_receivers SLR1 $leaf_names
        place_design -no_psip -no_bufg_opt
        plg_probe::assert_slr $source_names SLR0
        plg_probe::assert_slr $leaf_names SLR1
        route_design
        plg::assert_routed $out/build/routed_baseline
        set capture [plg::capture {unit_0/receiver/D} $out/build/edit]
        plg::require [expr {[dict size [dict get $capture ff]] == 1}] "Fixture lost its changed-D FF"
        set receiver [plg::exact cell {unit_0/receiver}]
        set old [get_nets -of_objects [plg::exact pin {unit_0/receiver/D}]]
        set_property DONT_TOUCH false $receiver
        set_property DONT_TOUCH false $old
        disconnect_net -net $old -pinlist [plg::exact pin {unit_0/receiver/D}]
        set extnet [get_nets -quiet -of_objects [get_ports ext]]
        if {![llength $extnet]} {
            create_net external_data
            set extnet [get_nets external_data]
            connect_net -net $extnet -objects [get_ports ext]
        }
        connect_net -net $extnet -objects [plg::exact pin {unit_0/receiver/D}]
        set_property DONT_TOUCH true $receiver
        set witnesses [plg_probe::ordinary_witnesses $source_pins $out/build/ordinary_witnesses.tsv]
        # Use all FF sites only to exercise multiple legacy batches. Both modes
        # receive this identical explicit scope plus the captured surviving D net.
        set sites {}
        foreach loc [plg::values LOC [get_cells -hierarchical -filter {REF_NAME =~ FD*}]] {
            if {[string match SLICE_* $loc]} {dict set sites $loc 1}
        }
        set context [dict create sites [lsort [dict keys $sites]] old_nets [dict get $capture old_nets] \
            changed_ff [dict get $capture ff] ordinary_witnesses $witnesses \
            part [get_property PART [current_design]] version [version -short]]
        plg_probe::save_dict $out/cleanup_context.tcldict $context
        write_checkpoint $out/baseline_edited.dcp
        plg_probe::save_dict $out/build/NATIVE_COMPLETE $context
    } else {
        set context [plg_probe::read_dict $out/cleanup_context.tcldict]
        open_checkpoint $out/baseline_edited.dcp
        plg::require [expr {[get_property PART [current_design]] eq [dict get $context part] && [version -short] eq [dict get $context version]}] "Probe checkpoint/backend mismatch"
        plg_probe::route_state $out/$mode/before.tsv
        report_route_status -file $out/$mode/before_route_status.rpt
        set begin [clock milliseconds]
        if {$mode eq "legacy"} {
            set result [plg::clean_sites_legacy512 [dict get $context sites] $out/$mode/cleanup [dict get $context old_nets]]
        } else {
            set result [plg::clean_sites [dict get $context sites] $out/$mode/cleanup [dict get $context old_nets]]
        }
        dict set result cleanup_elapsed_ms [expr {[clock milliseconds]-$begin}]
        plg_probe::route_state $out/$mode/after.tsv
        report_route_status -file $out/$mode/after_route_status.rpt
        set f [open $out/$mode/native_context.tsv w];puts $f "key\tvalue"
        foreach key {completed batch_size ordinary_nets clock_aliases ordinary_completed_calls physical_constant_completed_calls cleanup_elapsed_ms} {
            puts $f "$key\t[dict get $result $key]"
        }
        foreach key {ordinary_started_calls exact_native_queries max_native_collection_size gather_ms preflight_ms exact_ms ordinary_unroute_ms physical_constant_ms output_ms total_ms} {
            if {[dict exists $result $key]} {puts $f "$key\t[dict get $result $key]"}
        }
        foreach {key value} [list version [version -short] part [get_property PART [current_design]] checkpoint $out/baseline_edited.dcp] {puts $f "$key\t$value"}
        close $f
        plg_probe::save_dict $out/$mode/NATIVE_COMPLETE $result
    }
    close_design
} message options]} {
    puts stderr [dict get $options -errorinfo]
    exit 1
}
exit 0
