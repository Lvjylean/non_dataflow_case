# Benchmark the actual cache accessors, not an inlined Tcl dict expression.
# OLD_CODE NEW_CODE SNAPSHOT OUTPUT. No design or native-query equivalence claim:
# native metadata/clock guards are covered by candidate_readback_compare_v2.
if {[catch {
lassign $argv old code snapshot output tracing_expected
if {$tracing_expected eq ""} {set tracing_expected 1}
if {[file exists $output]} {error "Refusing to overwrite function probe evidence"}
file mkdir $output
source $snapshot
array set records [dict get $locality_reuse_snapshot cells]
set eligible {}
foreach name [lsort [array names records]] {
    if {[dict exists $records($name) I0]} {lappend eligible $name}
}
if {[llength $eligible]<32} {error "Real-cache function probe needs 32 LUT inputs"}
set cases {}
for {set i 0} {$i<32} {incr i} {
    set name [lindex $eligible [expr {$i*([llength $eligible]-1)/31}]]
    set pins {};foreach pin [dict keys $records($name)] {lappend pins $name/$pin}
    lappend cases [list $name $pins]
}
# Fixed read-context metadata isolates the cache functions from native queries.
namespace eval vs {variable active 1;variable epoch 1}
proc vs::assert_readable {} {}
namespace eval rf {}
proc rf::known_protected_ip {name} {return 0}
namespace eval lb {}
proc lb::input_source {ref pin} {return 1}
namespace eval locality_inventory {variable shared_active 1;variable capture_epoch 1}
proc locality_inventory::cell_metadata {name} {return [dict create name $name ref LUT1 slr SLR0 x 0 y 0]}
array set reference {}
set f [open $output/performance.tsv w];puts $f "mode\telapsed_us\tcalls"
foreach {mode root} [list old $old new $code] {
    source $root/code/regional/locality_input_snapshot.tcl
    set ::locality_inventory::connection_epoch 1
    set ::locality_inventory::connection_counters {mode enabled}
    if {$mode eq "old"} {
        set ::locality_inventory::connection_snapshot $locality_reuse_snapshot
    } else {locality_inventory::connection_install $locality_reuse_snapshot}
    dict for {key item} [dict get $locality_reuse_snapshot nets] {set ::locality_inventory::connection_clockless($key) 1}
    set tick [clock microseconds]
    foreach pair $cases {
        lassign $pair name pins
        set value [locality_inventory::connection_inputs $name $pins]
        if {$mode eq "old"} {set reference($name) $value} elseif {$reference($name) ne $value} {error "Accessor mismatch: $name"}
    }
    set elapsed($mode) [expr {[clock microseconds]-$tick}]
    puts $f "$mode\t$elapsed($mode)\t[llength $cases]";flush $f
}
close $f
if {$tracing_expected && $elapsed(new)*2 >= $elapsed(old)} {error "Actual accessor speed improvement below 2x: [array get elapsed]"}
set f [open $output/PASS w]
puts $f [list status PASS cases [llength $cases] equivalent true speedup [expr {double($elapsed(old))/$elapsed(new)}] scope actual_cache_functions_with_fixed_metadata]
close $f
puts "INPUT_FUNCTION_COMPLETE $output"
} message options]} {puts stderr [dict get $options -errorinfo];exit 1}
exit 0
