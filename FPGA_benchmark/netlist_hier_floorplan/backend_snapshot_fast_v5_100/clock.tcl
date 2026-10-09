proc compilefast_clock {out apply} {
    set period $::env(COMPILEFAST_PERIOD)
    if {![string is double -strict $period] || $period <= 0} {error "Invalid clock period"}
    set port_name ap_clk
    if {[info exists ::env(COMPILEFAST_CLOCK_PORT)]} {set port_name $::env(COMPILEFAST_CLOCK_PORT)}
    set ports [get_ports -quiet [list $port_name]]
    set clocks [get_clocks -quiet -of_objects $ports]
    if {[llength $ports] != 1 || [llength $clocks] != 1} {error "Expected one primary clock on port $port_name"}
    set c [lindex $clocks 0]
    if {[get_property IS_GENERATED $c]} {error "Expected primary clock"}
    set name [get_property NAME $c]; set before [get_property PERIOD $c]
    set jitter [get_property INPUT_JITTER $c]
    set changed [expr {$apply && abs($before-$period)>0.000001}]
    if {$changed} {
        set waveform {}
        foreach edge [get_property WAVEFORM $c] {lappend waveform [expr {double($edge)*$period/$before}]}
        create_clock -name $name -period $period -waveform $waveform $ports
        if {$jitter ne ""} {set_input_jitter [get_clocks $name] $jitter}
    }
    set c [get_clocks $name]
    if {abs([get_property PERIOD $c]-$period)>0.000001} {error "Clock period mismatch"}
    set f [open $out/clock.tsv w]
    puts $f "clock\tperiod_before\tperiod_after\twaveform\tinput_jitter\tchanged"
    puts $f "$name\t$before\t[get_property PERIOD $c]\t[get_property WAVEFORM $c]\t[get_property INPUT_JITTER $c]\t$changed"
    close $f
}
