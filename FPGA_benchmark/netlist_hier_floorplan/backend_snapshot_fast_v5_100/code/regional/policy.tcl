# Pure policy helpers; no Vivado state is accessed here.
namespace eval sb {}
proc sb::data_input_kind {ref pin} {
    # Classify the existing FF's D source; the source itself is never copied.
    if {[string match FD* $ref] && $pin eq "Q"} {return ff}
    if {[regexp {^RAMB(18|36)E[12]$} $ref] &&
        [regexp {^(DOUTADOUT|DOUTBDOUT|DOUTPADOUTP|DOUTPBDOUTP|DOADO|DOBDO|DOPADOP|DOPBDOP)\[[0-9]+\]$} $pin]} {return bram_data}
    if {[regexp {^URAM288(_BASE)?$} $ref] && [regexp {^DOUT_[AB]\[[0-9]+\]$} $pin]} {return uram_data}
    return unsupported
}
proc sb::require {ok message} {if {!$ok} {error $message}}
proc sb::family {name} {
    # Only normalize the leaf register bit, never hierarchy instance numbers.
    if {[regsub {\[[0-9]+\]$} $name {[]} result]} {return $result}
    regsub {([A-Za-z_])([0-9]+)$} $name {\1#} result
    return $result
}
proc sb::one_bit {value {default 0}} {
    set v [string tolower [string trim $value]]
    if {$v eq ""} {return $default}
    if {$v in {0 false}} {return 0}
    if {$v in {1 true}} {return 1}
    if {[regexp {^[0-9]+'[bhd]([01])$} $v unused bit]} {return $bit}
    error "Unsupported bit value: $value"
}
proc sb::slr_number {slr} {
    require [regexp {^SLR([0-9]+)$} $slr unused n] "Unknown SLR name: $slr"
    return $n
}
proc sb::boundary {a b} {expr {abs([slr_number $a]-[slr_number $b])}}
proc sb::ce_gain {source target input_slrs load_count} {
    set old [expr {$load_count * [boundary $source $target]}]
    set new 0
    foreach slr $input_slrs {incr new [boundary $slr $target]}
    # Existing input routing is retained; new inputs are the replication cost.
    return [expr {$old - $new}]
}
proc sb::chunks {items limit} {
    require [expr {$limit > 0}] "Invalid fanout limit"
    set result {}
    for {set i 0} {$i < [llength $items]} {incr i $limit} {
        lappend result [lrange $items $i [expr {$i+$limit-1}]]
    }
    return $result
}
proc sb::name_chunks {names limit} {
    # Only complete ordinary Tcl name lists belong here. Native collections
    # must keep using chunks: standard Tcl can truncate their display string.
    require [expr {[string is integer -strict $limit] && $limit > 0}] "Invalid name batch limit"
    set length_command ::llength
    set range_command ::lrange
    set append_command ::lappend
    foreach command {llength lrange lappend} variable {length_command range_command append_command} {
        if {[namespace which -command ::tcl::$command] ne ""} {set $variable ::tcl::$command}
    }
    set count [$length_command $names]
    set result {}
    for {set i 0} {$i < $count} {incr i $limit} {
        $append_command result [$range_command $names $i [expr {$i+$limit-1}]]
    }
    return $result
}
