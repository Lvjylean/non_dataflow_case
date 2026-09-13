# Preserve the reset truth table with one-level identity LUT buffers.
set port [get_ports ap_rst_n]
set rootnet [get_nets -of_objects $port]
set sinks [lsort [get_pins -leaf -of_objects $rootnet -filter {DIRECTION == IN}]]
set original_count [llength $sinks]
if {$original_count <= 256} {error "Reset does not require buffering"}
set branches [expr {($original_count+255)/256}]
if {$branches > 256} {error "One-level tree capacity exceeded"}
set count_before [llength [get_cells -hier -filter {IS_PRIMITIVE == 1}]]
set f [open reset_buffer_map.tsv w]
puts $f "buffer\toriginal_sink"
set all_after {}
for {set i 0} {$i < $branches} {incr i} {
    set group [lrange $sinks [expr {$i*256}] [expr {$i*256+255}]]
    set name orb_reset_buf_$i
    create_cell -reference LUT1 $name
    set cell [get_cells $name]
    set_property INIT 2'h2 $cell
    set_property DONT_TOUCH true $cell
    create_net ${name}_out
    set net [get_nets ${name}_out]
    connect_net -net $rootnet -objects [get_pins $name/I0]
    connect_net -net $net -objects [get_pins $name/O]
    foreach sink $group {
        set pin [get_pins $sink]
        set old [get_nets -of_objects $pin]
        disconnect_net -net $old -objects $pin
        connect_net -hierarchical -net $net -objects $pin
        puts $f "$name\t$sink"
    }
    set actual [lsort [get_pins -leaf -of_objects $net -filter {DIRECTION == IN}]]
    if {$actual ne $group} {error "Reset connectivity mismatch for $name"}
    set all_after [concat $all_after $actual]
    set_property DONT_TOUCH true $net
}
close $f
if {[lsort $all_after] ne $sinks} {error "Reset sink coverage mismatch"}
if {[llength [get_pins -leaf -of_objects $rootnet -filter {DIRECTION == IN}]] != $branches} {error "Unexpected root fanout"}
if {[llength [get_cells -hier -filter {IS_PRIMITIVE == 1}]] != $count_before+$branches} {error "Unexpected primitive change"}
set f [open reset_buffer_verified.txt w]
puts $f "original_sinks=$original_count branches=$branches max_branch=256 identity_LUT1_INIT=2'h2 no_registers_added=1 exact_sink_coverage=1"
close $f
