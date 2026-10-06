set ::env(COMPILEFAST_PERIOD) 8.7
set ::period 9.2
set ::generated 0
set ::ports ap_clk
set ::waveform {0.0 4.6}
set ::jitter 0.092
set ::creates 0
proc get_ports {args} {
    set ::requested_port [lindex $args end]
    return $::ports
}
proc get_clocks {args} {return ap_clk}
proc get_property {key object} {
    switch $key {
        IS_GENERATED {return $::generated}
        NAME {return ap_clk}
        PERIOD {return $::period}
        INPUT_JITTER {return $::jitter}
        WAVEFORM {return $::waveform}
        default {error "Unexpected property $key"}
    }
}
proc create_clock {args} {
    incr ::creates
    set ::period [lindex $args [expr {[lsearch -exact $args -period] + 1}]]
    set ::waveform [lindex $args [expr {[lsearch -exact $args -waveform] + 1}]]
    set ::jitter ""
}
proc set_input_jitter {object value} {set ::jitter $value}
source [lindex $argv 0]
set out [lindex $argv 1]
file mkdir $out
if {![catch {compilefast_clock $out 0}]} {error "Wrong period accepted"}
set ::generated 1
if {![catch {compilefast_clock $out 1}]} {error "Generated clock accepted"}
set ::generated 0
set ::ports {ap_clk other}
if {![catch {compilefast_clock $out 1}]} {error "Multiple ports accepted"}
set ::ports ap_clk
compilefast_clock $out 1
if {$::period != 8.7 || $::waveform ne {0.0 4.35} || $::jitter != 0.092} {error "Clock mutation mismatch"}
compilefast_clock $out 0
if {$::creates != 1} {error "Read-only check changed the clock"}
set ::env(COMPILEFAST_CLOCK_PORT) system_clock
set ::ports system_clock
set ::waveform {1.0 3.0}
compilefast_clock $out 1
if {$::requested_port ne "system_clock" || $::creates != 1 || $::waveform ne {1.0 3.0}} {
    error "Same-period custom clock was recreated or wrong port queried"
}
set ::env(COMPILEFAST_PERIOD) 6.5
set ::waveform {0.0 4.35}
compilefast_clock $out 1
if {$::period != 6.5 || $::waveform ne {0.0 3.25} || $::jitter != 0.092} {error "6.5ns clock mismatch"}
compilefast_clock $out 0
puts PASS
