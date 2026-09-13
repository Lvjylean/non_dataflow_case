# Split BRAM broadcasts with identity LUTs, without sequential changes.
set f [open bram_buffer_map.tsv w]; puts $f "buffer\toriginal_sink"
set idx 0; set modified 0; set original_total 0
set seen [dict create]
foreach candidate [get_nets -hier -segments -top_net_of_hierarchical_group -filter {FLAT_PIN_COUNT > 256}] {
    set drivers [get_pins -quiet -leaf -of_objects $candidate -filter {DIRECTION == OUT}]
    if {[llength $drivers] != 1} {continue}
    set driver [lindex $drivers 0]
    if {[dict exists $seen $driver]} {continue}
    dict set seen $driver 1
    if {![string match RAMB* [get_property REF_NAME [get_cells -of_objects $driver]]]} {continue}
    set rootnet [get_nets -of_objects $driver]
    set sinks [lsort [get_pins -leaf -of_objects $rootnet -filter {DIRECTION == IN}]]
    set n [llength $sinks]
    if {$n <= 256} {continue}
    incr modified; incr original_total $n
    set branches [expr {($n+127)/128}]
    if {$branches > 256} {error "BRAM branch root exceeds cap"}
    set all_after {}
    for {set i 0} {$i < $branches} {incr i} {
        set group [lrange $sinks [expr {$i*128}] [expr {$i*128+127}]]
        set name orb_bram_buf_$idx; incr idx
        create_cell -reference LUT1 $name
        set_property INIT 2'h2 [get_cells $name]
        set_property DONT_TOUCH true [get_cells $name]
        create_net ${name}_out
        set net [get_nets ${name}_out]
        connect_net -hierarchical -net $rootnet -objects [get_pins $name/I0]
        connect_net -net $net -objects [get_pins $name/O]
        foreach sink $group {
            set pin [get_pins $sink]
            disconnect_net -net [get_nets -of_objects $pin] -objects $pin
            connect_net -hierarchical -net $net -objects $pin
            puts $f "$name\t$sink"
        }
        set actual [lsort [get_pins -leaf -of_objects $net -filter {DIRECTION == IN}]]
        if {$actual ne $group} {error "BRAM sink mismatch $name"}
        set all_after [concat $all_after $actual]
        set_property DONT_TOUCH true $net
    }
    if {[lsort $all_after] ne $sinks} {error "BRAM coverage mismatch"}
    if {[llength [get_pins -leaf -of_objects $rootnet -filter {DIRECTION == IN}]] != $branches} {error "BRAM root mismatch"}
}
close $f
if {$modified == 0} {error "No oversized BRAM broadcast found"}
set f [open bram_buffer_verified.txt w]
puts $f "modified_outputs=$modified original_sinks=$original_total added_identity_LUT1=$idx max_initial_branch=128 exact_sink_coverage=1"
close $f
