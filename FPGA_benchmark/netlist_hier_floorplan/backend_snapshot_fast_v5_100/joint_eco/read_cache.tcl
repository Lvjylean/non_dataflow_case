# Read-only, phase-scoped observations. No cache survives a netlist mutation.
namespace eval fc {
    variable active 0
    variable objects; array set objects {}
    variable pins; array set pins {}
    variable values; array set values {}
    variable stats; array set stats {}
    variable networks; array set networks {}
    variable pin_network; array set pin_network {}
    variable clock_network; array set clock_network {}
    variable anchors; array set anchors {}
    variable started
    variable label
    variable output
}
proc fc::count {key} {variable stats; if {![info exists stats($key)]} {set stats($key) 0}; incr stats($key)}
proc fc::progress {stage n total} {
    variable label
    if {$n == 1 || $n % 256 == 0 || $n == $total} {
        puts "FAST_CHECK [clock seconds] $label $stage $n/$total"; flush stdout
    }
}
proc fc::clear {} {
    foreach table {objects pins values stats networks pin_network clock_network anchors} {variable $table; array unset $table *}
    foreach table {cell_objects pin_objects refs positions} {array unset ::sb::$table *}
    set ::sb::signal_cache {}
}
proc fc::cell {name} {
    variable active;variable objects
    if {!$active} {return [sb::uncached_cell $name]}
    if {![info exists objects($name)]} {count cell_miss;set objects($name) [sb::uncached_cell $name]} else {count cell_hit}
    return $objects($name)
}
proc fc::pin {name} {
    variable active;variable pins
    if {!$active} {return [sb::uncached_pin $name]}
    if {![info exists pins($name)]} {
        count pin_cell_fetch
        set pp [get_pins -quiet -of_objects [cell [file dirname $name]]]
        foreach obj $pp n [sb::names $pp] {set pins($n) $obj}
    } else {count pin_hit}
    sb::require [info exists pins($name)] "Missing pin: $name"
    return $pins($name)
}
proc fc::observe {op name} {
    variable active;variable values
    if {!$active} {return [::sb::uncached_$op $name]}
    set key [list $op $name]
    if {![info exists values($key)]} {
        count ${op}_miss
        if {$op in {signal loads drivers canonical}} {
            set values($key) [fc::connectivity $op $name]
        } else {set values($key) [::sb::uncached_$op $name]}
    } else {count ${op}_hit}
    return $values($key)
}

# Observe each complete native electrical network once, including unexpected loads.
# Membership comes exclusively from Vivado, never from expected plan connections.
proc fc::network {name} {
    variable networks;variable pin_network
    if {[info exists pin_network($name)]} {count network_hit;return $networks($pin_network($name))}
    set po [pin $name]
    set segments [get_nets -quiet -segments -of_objects $po]
    set top [get_nets -quiet -top_net_of_hierarchical_group -segments $segments]
    sb::require [expr {[llength $top]==1}] "Expected one connected signal: $name"
    set id [get_property NAME $top]
    if {![info exists networks($id)]} {
        count network_fetch
        set observed [get_pins -quiet -of_objects $segments -filter {IS_LEAF == 1}]
        set inputs {};set outputs {};set allnames [sb::names $observed]
        foreach pn $allnames direction [sb::values DIRECTION $observed] {
            if {$direction eq "IN"} {lappend inputs $pn}
            if {$direction eq "OUT"} {lappend outputs $pn}
        }
        set inputs [lsort -unique $inputs];set outputs [lsort -unique $outputs]
        if {[llength $outputs]} {set sig [list drivers $outputs]} else {
            set sig [list ports [lsort [sb::names [get_ports -quiet -of_objects $segments]]]]
        }
        set networks($id) [dict create canonical $id loads $inputs drivers $outputs signal $sig]
        foreach pn $allnames {set pin_network($pn) $id}
    }
    set pin_network($name) $id
    return $networks($id)
}

proc fc::clock_canonical {pin net} {
    variable clock_network
    sb::require [expr {[llength $net]==1}] "Expected one connected clock signal: $pin"
    set name [get_property NAME $net]
    if {![info exists clock_network($name)]} {
        count clock_network_fetch
        set segments [get_nets -quiet -segments $net]
        set top [get_nets -quiet -top_net_of_hierarchical_group -segments $segments]
        sb::require [expr {[llength $top]==1}] "Expected one connected clock signal: $pin"
        set top_name [get_property NAME $top]
        foreach segment [sb::names $segments] {set clock_network($segment) $top_name}
        set clock_network($name) $top_name
    } else {count clock_network_hit}
    return $clock_network($name)
}
proc fc::connectivity {op name} {
    if {$op eq "signal"} {
        # Preserve the original constant and FF-clock interpretation exactly.
        set net [get_nets -of_objects [pin $name]];set type [get_property TYPE $net]
        if {$type in {GROUND POWER}} {return [list constant $type]}
        if {[file tail $name] eq "C" && [get_property REF_NAME [cell [file dirname $name]]] in {FDRE FDSE}} {
            return [list clock [fc::clock_canonical $name $net]]
        }
    }
    return [dict get [network $name] $op]
}
proc fc::members {pb} {
    variable active;variable values
    set key [list pblock_members [get_property NAME $pb]]
    if {!$active} {return [sb::names [get_cells -of_objects $pb]]}
    if {![info exists values($key)]} {count pblock_fetch;set values($key) [sb::names [get_cells -of_objects $pb]]}
    return $values($key)
}

proc fc::seed_local {local} {
    variable anchors;array unset anchors *
    dict for {key meta} [dict get $local snapshot nets] {
        if {[dict get $meta kind] eq "ordinary" && [lindex [dict get $meta signal] 0] eq "drivers"} {
            set anchors($key) $key
        } else {set anchors($key) [dict get $meta anchor]}
    }
}
proc fc::planned_loads {key} {
    variable anchors
    if {[info exists anchors($key)]} {return [sb::loads $anchors($key)]}
    return [sb::loads $key]
}
proc fc::net_loads {local key} {
    if {[dict exists $local snapshot nets $key]} {
        set net [dict get $local snapshot nets $key]
        if {[dict get $net kind] ne "ordinary" || [lindex [dict get $net signal] 0] ne "drivers"} {
            return [sb::loads [dict get $net anchor]]
        }
    }
    return [sb::loads $key]
}
proc fc::mutation_guard {command op} {
    variable active
    if {$active} {error "FAST_CHECK_MUTATION_FORBIDDEN: [lindex $command 0] inside read-only verification"}
}
proc fc::begin {name out names} {
    variable active;variable objects;variable pins;variable started;variable label;variable output
    sb::require [expr {!$active}] "Nested read-only cache phase"
    clear;set started [clock milliseconds];set label $name;set output $out;set active 1
    file mkdir $out
    puts "FAST_CHECK [clock seconds] $name begin cells=[llength $names]";flush stdout
    set done 0;set names [lsort -unique $names]
    foreach batch [sb::chunks $names 512] {
        set cc [get_cells -quiet $batch];set nn [sb::names $cc]
        sb::require [expr {[lsort $nn] eq [lsort $batch]}] "Missing/ambiguous batch cell"
        foreach obj $cc n $nn {set objects($n) $obj}
        set pp [get_pins -quiet -of_objects $cc]
        foreach obj $pp n [sb::names $pp] {set pins($n) $obj}
        incr done [llength $batch];progress prefetch $done [llength $names]
    }
}
proc fc::end {} {
    variable active;variable started;variable label;variable output;variable stats
    set elapsed [expr {([clock milliseconds]-$started)/1000.0}]
    set path $output/verification_runtime.tsv;set first [expr {![file exists $path]}]
    set f [open $path a];if {$first} {puts $f "phase\tseconds\tcounters"}
    puts $f "$label\t$elapsed\t[array get stats]";close $f
    puts "FAST_CHECK [clock seconds] $label end seconds=$elapsed counters=[array get stats]";flush stdout
    set active 0;clear
}
proc fc::with {label out names body} {
    set rc [catch {begin $label $out $names; uplevel 1 $body} result options]
    if {$::fc::active} {end}
    return -options $options $result
}
proc fc::names_for {plan spec prior {edited 0}} {
    set cells {}
    dict for {name item} [dict get $spec clones] {
        lappend cells [dict get $item original]
        if {$edited} {lappend cells $name}
    }
    dict for {name item} [dict get $prior clones] {lappend cells $name}
    dict for {endpoint row} [dict get $spec targets] {lappend cells [file dirname $endpoint] [dict get $row original]}
    dict for {pin pair} [dict get $spec changes] {
        lappend cells [file dirname $pin] [file dirname [lindex $pair 0]]
    }
    if {[dict exists $plan local_broadcast]} {
        set local [dict get $plan local_broadcast]
        dict for {key item} [dict get $local snapshot roots] {lappend cells [dict get $item cell]}
        dict for {name item} [dict get $local graph replicas] {lappend cells $name}
        dict for {key sinks} [dict get $local graph expected] {
            if {[dict exists $local snapshot nets $key]} {lappend cells [file dirname [dict get $local snapshot nets $key anchor]]} else {lappend cells [file dirname $key]}
        }
    }
    return [lsort -unique $cells]
}
proc fc::install {} {
    foreach op {cell pin canonical loads drivers signal config ref} {
        rename ::sb::$op ::sb::uncached_$op
        if {$op in {cell pin}} {proc ::sb::$op {name} [format {return [::fc::%s $name]} $op]} else {
            proc ::sb::$op {name} [format {return [::fc::observe %s $name]} $op]
        }
    }
    # Keep every original verifier assertion. Replace only its observation calls.
    set body [info body ::lb::verify]
    set old {set seen [lsort -unique [sb::names [get_pins -quiet -of_objects [get_nets -segments $obj] -filter {IS_LEAF == 1 && DIRECTION == IN}]]]}
    sb::require [expr {[string first $old $body]>=0}] "Unknown output verifier source"
    set body [string map [list $old {set seen [fc::planned_loads $key]} {[sb::names [get_cells -of_objects $pb]]} {[fc::members $pb]}] $body]
    foreach {stage pattern total} [list inputs {foreach pin [array names expected_inputs]} {[array size expected_inputs]} outputs {dict for {key pins} [dict get $graph expected]} {[dict size [dict get $graph expected]]}] {
        set needle "$pattern \{"
        sb::require [expr {[string first $needle $body]>=0}] "Unknown verifier loop: $stage"
        set replacement "set done 0\n    $needle\n        fc::progress $stage \[incr done\] $total"
        set body [string map [list $needle $replacement] $body]
    }

    set init {set local [dict get $plan local_broadcast]; set snapshot [dict get $local snapshot]; set graph [dict get $local graph]}
    set replacement "$init\n    fc::seed_local \$local\n    array set lb_nets \[dict get \$snapshot nets\]\n    array set lb_roots \[dict get \$snapshot roots\]\n    array set lb_expected \[dict get \$graph expected\]"
    set body [string map [list $init $replacement {set obj [source_net $local $key]} {# Output anchor was resolved once in seed_local.} {[dict exists $snapshot nets $key]} {[info exists lb_nets($key)]} {[dict get $snapshot nets $key signal]} {[dict get $lb_nets($key) signal]} {set root [dict get $snapshot roots [dict get $item key]]} {set root $lb_roots([dict get $item key])} {[dict get $graph expected $name/[dict get $root pin]]} {$lb_expected($name/[dict get $root pin])}] $body]
    sb::require [expr {[string first {source_net $local $key} $body]<0}] "Large-plan hot-loop call remains"
    proc ::lb::verify {plan out placed} $body
    foreach cmd {set_property reset_property create_cell create_net remove_cell remove_net connect_net disconnect_net add_cells_to_pblock remove_cells_from_pblock create_pblock delete_pblocks resize_pblock place_design route_design phys_opt_design opt_design open_checkpoint close_design} {
        if {[llength [info commands ::$cmd]]} {trace add execution ::$cmd enter ::fc::mutation_guard}
    }
}
