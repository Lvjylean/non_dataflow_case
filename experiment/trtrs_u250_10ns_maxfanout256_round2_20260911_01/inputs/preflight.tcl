set run_dir $::env(RUN_DIR)
cd $run_dir
set_param general.maxThreads 4
open_checkpoint /Projects/jinyang/workspace/non_dataflow_crossSLR/case/experiment/vivado-trtrs-baseline-10ns-20260911-01/post_synth.dcp
set f [open preflight_high_fanout.tsv w]
puts $f "net\tflat_pin_count\tlogical_loads\tdriver_pin\tdriver_ref\tis_clock\tdont_touch"
set nets [get_nets -hier -filter {FLAT_PIN_COUNT > 256}]
puts "PREFLIGHT_CANDIDATE_SEGMENTS=[llength $nets]"
set seen [dict create]
foreach net $nets {
    set drivers [get_pins -quiet -leaf -of_objects $net -filter {DIRECTION == OUT}]
    set ports [get_ports -quiet -of_objects $net -filter {DIRECTION == IN}]
    set key [join [concat $drivers $ports] ,]
    if {$key eq ""} {set key $net}
    if {[dict exists $seen $key]} {continue}
    dict set seen $key 1
    set loads [get_pins -quiet -leaf -of_objects $net -filter {DIRECTION == IN}]
    set refs [get_property REF_NAME [get_cells -quiet -of_objects $drivers]]
    set isclock [get_property IS_CLOCK $net]
    puts $f "$net\t[get_property FLAT_PIN_COUNT $net]\t[llength $loads]\t$key\t$refs\t$isclock\t[get_property DONT_TOUCH $net]"
    flush $f
}
close $f
report_high_fanout_nets -max_nets 100 -file preflight_high_fanout.rpt
report_clocks -file preflight_clocks.rpt
puts "PREFLIGHT_COMPLETE=[dict size $seen]"
close_design
