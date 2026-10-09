source [file join [file dirname [info script]] core.tcl]
source [file join [file dirname [info script]] regional.tcl]
proc assert {value message} {if {![uplevel 1 [list expr $value]]} {error $message}}
set protected {compute/ip/inst/i_synth/ADDSUB/NORM/DISTANCE[2]/I0}
set outside {compute/ip/inst/i_synth_external/D}
set memory {gmem1_m_axi_U/load_unit/buff_rdata/U_fifo_mem/mem_reg/DOUTADOUT[3]}
set good [dict create roots [list [dict create driver $memory sinks [list load/D $outside]]]]
rf::validate_edit_scope $good
assert {![rf::known_protected_ip $memory] && ![rf::known_protected_ip $outside]} "Ordinary data scope changed"
foreach pin [list $protected inst/i_synth/leaf/O] {
    set bad [dict create roots [list [dict create driver $pin sinks load/D]]]
    assert {[catch {rf::validate_edit_scope $bad} message] && [string match {Protected IP driver*} $message]} "Protected source plan accepted"
}
set bad [dict create roots [list [dict create driver $memory sinks [list load/D $protected]]]]
assert {[catch {rf::validate_edit_scope $bad} message] && [string match {Protected IP sink*} $message]} "External source to protected sink accepted"
# Missing config guarantees that the guard executes before configuration, I/O,
# native queries, or any mutation in apply; the error must be the scope guard.
assert {[catch {rf::apply $bad unused} message] && [string match {Protected IP sink*} $message]} "Saved-plan guard is too late"
puts "PASS: protected drivers and sinks excluded, ordinary RAM retained, unsafe saved plans rejected before mutation"
