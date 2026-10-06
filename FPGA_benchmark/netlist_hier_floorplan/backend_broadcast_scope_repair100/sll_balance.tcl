# Temporary, disconnected-from-functional-data Laguna capacity reservations.
namespace eval sllph {variable prefix sllph_; variable active 0; variable records {}; variable logdir {}}

proc sllph::names {objects} {
    if {![llength $objects]} {return {}}
    return [get_property NAME $objects]
}
proc sllph::catalog {} {
    set tiles [get_tiles -quiet -filter {TYPE =~ LAG_LAG*}]
    set nodes [get_nodes -quiet -of_objects $tiles -filter {IS_SLL == 1 && IS_CROSSING_SLRS == 1}]
    if {![llength $nodes]} {error "No native SLL nodes found"}
    set columns {}; set grouped {}
    foreach name [names $nodes] boundaries [get_property CROSSING_SLRS $nodes] {
        if {![regexp {^LAG_LAG_X([0-9]+)Y[0-9]+/} $name -> x]} {error "Unrecognized SLL node $name"}
        set boundaries [lsort -dictionary $boundaries]
        if {[llength $boundaries] != 2} {error "Invalid SLL boundary $name: $boundaries"}
        set key [join $boundaries -]
        dict lappend grouped $key,$x $name
        lappend columns $x
    }
    set columns [lsort -unique -integer $columns]
    if {[llength $columns] != 16} {error "Expected 16 U250 SLL columns"}
    set result {}; set idx 0
    foreach x $columns {
        foreach boundary {SLR0-SLR1 SLR1-SLR2 SLR2-SLR3} {
            set group [lsort -unique -dictionary [dict get $grouped $boundary,$x]]
            if {[llength $group] != 1440} {error "Unexpected SLL capacity $boundary column $idx"}
            dict set result $boundary,$idx [dict create tile_x $x nodes $group capacity 1440]
        }
        incr idx
    }
    return $result
}
proc sllph::endpoints {name lower upper} {
    set node [get_nodes $name]
    set tx {}; set rx {}
    foreach up [get_nodes -uphill -of_objects $node] {
        if {![string match *TXOUT [get_property NAME $up]]} {continue}
        foreach pin [get_site_pins -quiet -of_objects [get_nodes -uphill -of_objects $up]] {
            set pn [get_property NAME $pin]
            if {![regexp {^(LAGUNA_X[0-9]+Y[0-9]+)/TXQ([0-9]+)$} $pn -> site index]} {continue}
            if {[get_property NAME [get_slrs -of_objects [get_sites $site]]] eq $lower} {lappend tx [list $site TX_REG$index]}
        }
    }
    foreach pin [get_site_pins -quiet -of_objects [get_nodes -downhill -of_objects $node]] {
        set pn [get_property NAME $pin]
        if {![regexp {^(LAGUNA_X[0-9]+Y[0-9]+)/RXD([0-9]+)$} $pn -> site index]} {continue}
        if {[get_property NAME [get_slrs -of_objects [get_sites $site]]] eq $upper} {lappend rx [list $site RX_REG$index]}
    }
    if {[llength $tx] != 1 || [llength $rx] != 1} {error "Ambiguous native TX/RX mapping: $name $tx $rx"}
    return [list [lindex $tx 0] [lindex $rx 0]]
}
proc sllph::assert_absent {} {
    if {[llength [get_cells -quiet -hier -filter {NAME =~ sllph_*}]] || [llength [get_nets -quiet -hier -filter {NAME =~ sllph_*}]]} {
        error "Temporary SLL objects remain in the functional design"
    }
}
# Unset DONT_TOUCH may be an empty string on an OOC top-level clock net.
proc sllph::is_protected {net} {
    return [string is true -strict [get_property DONT_TOUCH $net]]
}
# all_registers also returns RAM/DSP sequential cells; choose a real FF clock pin.
proc sllph::resolve_clock {clock_port} {
    set port [get_ports -quiet [list $clock_port]]
    if {[llength $port] != 1} {error "SLL placeholders require one source clock port: $clock_port"}
    set clock [get_clocks -quiet -of_objects $port]
    if {[llength $clock] != 1} {error "SLL placeholders require one declared source clock"}
    set registers [all_registers -clock $clock -cells]
    set flops [filter $registers {REF_NAME == FDRE || REF_NAME == FDSE || REF_NAME == FDCE || REF_NAME == FDPE}]
    if {![llength $flops]} {error "No supported FF clock pin in SLL source clock domain $clock_port"}
    set ff [lindex $flops 0]
    set cpin [get_pins -quiet -of_objects $ff -filter {REF_PIN_NAME == C}]
    if {[llength $cpin] != 1} {error "SLL source FF has no unique C pin: $ff"}
    set clocknet [get_nets -quiet -top_net_of_hierarchical_group -segments -of_objects $cpin]
    if {[llength $clocknet] != 1} {error "Cannot resolve the clock net of FF $ff"}
    return [dict create port $port clock $clock ff $ff pin $cpin net $clocknet]
}
proc sllph::install {plan out} {
    variable active; variable records; variable logdir
    if {$active} {error "SLL placeholders already installed"}
    assert_absent
    source $plan
    if {![info exists sll_plan] || [dict get $sll_plan schema] ne "u250-sll-reservation-v1"} {error "Invalid SLL plan"}
    if {[get_property PART [current_design]] ne "xcu250-figd2104-2L-e"} {error "SLL catalog is validated for U250 only"}
    set logdir $out; file mkdir $out
    set clock_binding [resolve_clock [dict get $sll_plan clock_port]]
    set cf [open $out/clock_binding.tsv w]
    puts $cf "property\tvalue"
    dict for {key object} $clock_binding {puts $cf "$key\t[names $object]"}
    close $cf
    set cat [catalog]; set records {}; set used {}; set serial 0
    foreach bundle [dict get $sll_plan bundles] {
        lassign $bundle lower upper column
        set key $lower-$upper,$column
        set nodes [dict get $cat $key nodes]
        # Exactly one third, evenly interleaved throughout all 60 Laguna tiles.
        for {set i 0} {$i < [llength $nodes]} {incr i 3} {
            set node [lindex $nodes $i]
            lassign [endpoints $node $lower $upper] tx rx
            foreach endpoint [list $tx $rx] {
                lassign $endpoint site bel
                set full $site/$bel
                if {[dict exists $used $full] || [llength [get_cells -quiet -of_objects [get_bels $full]]]} {error "Unavailable SLL endpoint $full"}
                dict set used $full 1
            }
            lappend records [dict create id $serial node $node bundle $key tx $tx rx $rx]
            incr serial
        }
    }
    set clocknet [dict get $clock_binding net]
    set clock_was_protected [is_protected $clocknet]
    if {$clock_was_protected} {set_property DONT_TOUCH false $clocknet}
    if {[llength $records]} {
        create_cell -reference VCC sllph_vcc
        create_cell -reference GND sllph_gnd
        create_net sllph_one; create_net sllph_zero
        connect_net -net [get_nets sllph_one] -objects [get_pins sllph_vcc/P]
        connect_net -net [get_nets sllph_zero] -objects [get_pins sllph_gnd/G]
        foreach rec $records {
            set id [dict get $rec id]
            foreach role {tx rx} {
                set cell sllph_${role}_$id
                create_cell -reference FDRE $cell
                connect_net -net $clocknet -objects [get_pins $cell/C]
                connect_net -net [get_nets sllph_one] -objects [get_pins $cell/CE]
                connect_net -net [get_nets sllph_zero] -objects [get_pins $cell/R]
            }
            connect_net -net [get_nets sllph_zero] -objects [get_pins sllph_tx_$id/D]
            create_net sllph_link_$id
            connect_net -net [get_nets sllph_link_$id] -objects [get_pins [list sllph_tx_$id/Q sllph_rx_$id/D]]
            set_property DONT_TOUCH true [get_nets sllph_link_$id]
            foreach role {tx rx} {
                set cell [get_cells sllph_${role}_$id]
                lassign [dict get $rec $role] site bel
                set_property BEL $bel $cell
                set_property LOC $site $cell
                set_property USER_SLL_REG true $cell
                set_property DONT_TOUCH true $cell
            }
        }
        set_property DONT_TOUCH true [get_cells [list sllph_vcc sllph_gnd]]
    }
    if {$clock_was_protected} {set_property DONT_TOUCH true $clocknet}
    set active 1
    set f [open $out/reservations.tsv w]
    puts $f "id\tbundle\tnode\ttx_site\ttx_bel\trx_site\trx_bel"
    foreach rec $records {puts $f "[dict get $rec id]\t[dict get $rec bundle]\t[dict get $rec node]\t[join [dict get $rec tx] \t]\t[join [dict get $rec rx] \t]"}
    close $f
    verify installed 0
}
proc sllph::verify {stage routed} {
    variable records; variable logdir; variable active
    if {!$active} {error "SLL placeholders not active"}
    set seen {}
    foreach rec $records {
        set id [dict get $rec id]
        foreach role {tx rx} {
            set cell [get_cells sllph_${role}_$id]
            lassign [dict get $rec $role] site bel
            if {[llength $cell] != 1 || [get_property LOC $cell] ne $site || [get_property BEL $cell] ni [list $bel LAGUNA.$bel] || ![get_property IS_LOC_FIXED $cell] || ![get_property IS_BEL_FIXED $cell]} {error "Placeholder endpoint mismatch: $role $id expected $site $bel actual [get_property LOC $cell] [get_property BEL $cell] fixed [get_property IS_LOC_FIXED $cell] [get_property IS_BEL_FIXED $cell]"}
        }
        foreach role {tx rx} {
            foreach pin {C CE R D} {
                if {[llength [get_nets -quiet -of_objects [get_pins sllph_${role}_$id/$pin]]] != 1} {error "Disconnected placeholder pin $role $id $pin"}
            }
        }
        set net [get_nets sllph_link_$id]
        if {[lsort [names [get_pins -leaf -of_objects $net]]] ne [lsort [list sllph_tx_$id/Q sllph_rx_$id/D]]} {error "Placeholder link was modified $id"}
        if {$routed} {
            set actual [names [get_nodes -of_objects $net -filter {IS_SLL == 1 && IS_CROSSING_SLRS == 1}]]
            if {$actual ne [list [dict get $rec node]]} {error "Reserved net uses wrong SLL: $id $actual"}
            if {[dict exists $seen $actual]} {error "Duplicate reserved SLL $actual"}
            dict set seen $actual 1
        }
    }
    set f [open $logdir/$stage.tsv w]; puts $f "check\tvalue\nreserved_slls\t[llength $records]\nverified\t1\nrouted_exact_sll_verified\t$routed"; close $f
}
proc sllph::external_pins {nets} {
    set result {}
    foreach net $nets {
        foreach pin [get_pins -quiet -leaf -of_objects $net] {
            set name [get_property NAME $pin]
            if {![string match sllph_* $name]} {lappend result [list $name [get_property NAME $net]]}
        }
    }
    return [lsort $result]
}
proc sllph::remove {} {
    variable active; variable logdir
    verify final_placement 0
    set cells [get_cells -hier -filter {NAME =~ sllph_*}]
    set owned [get_nets -quiet -hier -filter {NAME =~ sllph_*}]
    set touched [get_nets -quiet -of_objects [get_pins -of_objects $cells]]
    set shared {}
    foreach net $touched {
        if {![string match sllph_* [get_property NAME $net]]} {lappend shared $net}
    }
    if {[llength [external_pins $owned]]} {error "Placeholder nets drive functional pins"}
    set before [external_pins $shared]
    set other_cells [llength [get_cells -hier -filter {IS_PRIMITIVE == 1 && NAME !~ sllph_*}]]
    set restore_protection {}
    foreach net $shared {if {[is_protected $net]} {lappend restore_protection $net}}
    if {[llength $restore_protection]} {set_property DONT_TOUCH false $restore_protection}
    if {[llength $owned]} {set_property DONT_TOUCH false $owned}
    if {[llength $cells]} {set_property DONT_TOUCH false $cells; remove_cell $cells}
    set owned [get_nets -quiet -hier -filter {NAME =~ sllph_*}]
    if {[llength $owned]} {set_property DONT_TOUCH false $owned; remove_net $owned}
    if {[llength $restore_protection]} {set_property DONT_TOUCH true $restore_protection}
    assert_absent
    if {[external_pins $shared] ne $before || [llength [get_cells -hier -filter {IS_PRIMITIVE == 1}]] != $other_cells} {error "Functional netlist changed while removing placeholders"}
    set f [open $logdir/removed.tsv w]; puts $f "check\tvalue\nall_temporary_objects_removed\t1\nfunctional_shared_connections_unchanged\t1\nfunctional_cell_count_unchanged\t1"; close $f
    set active 0
}

proc sllph::routed_usage {out} {
    set cat [catalog]
    # Preserve native collections; resolving 69k string node names is very slow.
    set all [get_nodes -quiet -of_objects [get_tiles -quiet -filter {TYPE =~ LAG_LAG*}] -filter {IS_SLL == 1 && IS_CROSSING_SLRS == 1}]
    file mkdir $out
    set f [open $out/routed_sll_bundles.tsv w]
    puts $f "boundary\tcolumn\ttile_x\tused_nodes\tcapacity\tutilization"
    set total 0
    foreach key [lsort -dictionary [dict keys $cat]] {
        lassign [split $key ,] boundary column
        set pair [join [split $boundary -] { }]
        set x [dict get $cat $key tile_x]
        set filter "CROSSING_SLRS == \"$pair\" && NAME =~ LAG_LAG_X${x}Y*"
        set group [filter $all $filter]
        if {[llength $group] != 1440} {error "Routed inventory geometry mismatch $key"}
        set nets [get_nets -quiet -of_objects $group]
        set used {}
        if {[llength $nets]} {
            set used [get_nodes -quiet -of_objects $nets -filter "IS_SLL == 1 && IS_CROSSING_SLRS == 1 && $filter"]
        }
        set count [llength $used]
        incr total $count
        puts $f "$boundary\t$column\t$x\t$count\t1440\t[expr {$count/1440.0}]"
        flush $f
    }
    close $f
    return $total
}
