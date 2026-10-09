# Shared physical contract for placed-netlist edits. No timing/fanout relaxation.
namespace eval plg {variable version 1}
proc plg::require {ok message} {if {!$ok} {error "PHYSICAL_ECO: $message"}}
proc plg::names {objects} {if {![llength $objects]} {return {}}; return [get_property NAME $objects]}
proc plg::values {key objects} {
    if {![llength $objects]} {return {}}
    set values [get_property $key $objects]
    if {[llength $objects] == 1} {return [list $values]}
    return $values
}
proc plg::batches {items} {
    set result {}
    for {set i 0} {$i < [llength $items]} {incr i 512} {lappend result [lrange $items $i [expr {$i+511}]]}
    return $result
}
proc plg::exact {kind names} {
    set names [lsort -unique $names]
    if {![llength $names]} {return {}}
    # Keep the native Vivado collection type; lappend converts handles to strings.
    set result [get_${kind}s -quiet $names]
    require [expr {[lsort [plg::names $result]] eq $names}] "Missing or ambiguous $kind objects"
    return $result
}
proc plg::capture {pins out} {
    file mkdir $out
    set ff {}; set sites {}; set old_nets {}
    foreach batch [batches [lsort -unique $pins]] {
        set objects [exact pin $batch]
        set dp [filter $objects {DIRECTION == IN && REF_PIN_NAME == D}]
        if {![llength $dp]} {continue}
        foreach name [names [get_nets -quiet -segments -of_objects $dp]] {dict set old_nets $name 1}
        set cells [get_cells -of_objects $dp -filter {REF_NAME =~ FD*}]
        foreach name [names $cells] loc [values LOC $cells] bel [values BEL $cells] {
            if {$loc eq ""} {continue}
            require [string match SLICE_* $loc] "Modified placed FF is outside a Slice: $name ($loc)"
            dict set ff $name [list $loc $bel]
            dict set sites $loc 1
        }
    }
    set f [open $out/changed_ff.tsv w]; puts $f "cell\told_loc\told_bel"
    dict for {name pos} $ff {puts $f [join [linsert $pos 0 $name] \t]}
    close $f
    return [dict create ff $ff sites [dict keys $sites] old_nets [dict keys $old_nets] out $out]
}
proc plg::collect_routes {nets normal_name constants_name} {
    upvar 1 $normal_name normal $constants_name constants
    foreach n [names $nets] type [values TYPE $nets] fixed [values IS_ROUTE_FIXED $nets] route [values FIXED_ROUTE $nets] {
        require [expr {$fixed ni {1 true TRUE} && [string trim $route " \t\r\n{}"] eq ""}] "Affected net has an explicit fixed route: $n"
        if {$type in {POWER GROUND}} {set constants 1; continue}
        dict set normal $n 1
    }
}
proc plg::cleanup_batch_size {} {
    # Bound each native collection independently of the full affected-net union.
    # 32768 objects reduce the historical 324177-net cleanup to ten calls.
    set size 32768
    if {[info exists ::env(PLG_CLEANUP_BATCH_SIZE)]} {set size $::env(PLG_CLEANUP_BATCH_SIZE)}
    require [expr {[string is integer -strict $size] && $size >= 1 && $size <= 1048576}] \
        "PLG_CLEANUP_BATCH_SIZE must be an integer in 1..1048576"
    return $size
}
proc plg::cleanup_metrics_write {out metrics} {
    set f [open $out/cleanup_metrics.tcldict w]
    puts $f $metrics
    close $f
}
proc plg::clean_sites {site_names out {old_nets {}}} {
    file mkdir $out
    set begin [clock milliseconds]
    set metrics [dict create completed 0 stage preflight batch_size [cleanup_batch_size] \
        ordinary_nets 0 clock_aliases 0 physical_constant_required 0 \
        ordinary_planned_calls 0 ordinary_started_calls 0 ordinary_completed_calls 0 \
        ordinary_completed_nets 0 exact_native_queries 0 max_native_collection_size 0 \
        physical_constant_started_calls 0 physical_constant_completed_calls 0 \
        discovery_ms 0 gather_ms 0 preflight_ms 0 exact_ms 0 ordinary_unroute_ms 0 physical_constant_ms 0 output_ms 0 total_ms 0]
    cleanup_metrics_write $out $metrics
    set f {}
    set code [catch {
        set normal {}; set clocks {}; set constants 0
        foreach batch [batches [lsort -unique $site_names]] {
            set gather_begin [clock milliseconds]
            set sites [exact site $batch]
            set cells [get_cells -quiet -of_objects $sites]
            if {![llength $cells]} {dict incr metrics gather_ms [expr {[clock milliseconds]-$gather_begin}]; continue}
            set pins [get_pins -quiet -of_objects $cells]
            set cp [filter $pins {IS_CLOCK == 1}]
            if {[llength $cp]} {
                foreach n [names [get_nets -quiet -segments -of_objects $cp]] {dict set clocks $n 1}
            }
            set dp [filter $pins {IS_CLOCK == 0}]
            if {![llength $dp]} {dict incr metrics gather_ms [expr {[clock milliseconds]-$gather_begin}]; continue}
            set nets [get_nets -quiet -segments -of_objects $dp]
            dict incr metrics gather_ms [expr {[clock milliseconds]-$gather_begin}]
            set step [clock milliseconds]
            collect_routes $nets normal constants
            dict incr metrics preflight_ms [expr {[clock milliseconds]-$step}]
        }
        # A disconnected old D net may no longer touch the site after the edit.
        # Deleted nets need no cleanup; surviving old segments must also be unrouted.
        foreach batch [batches $old_nets] {
            set step [clock milliseconds]
            set nets [get_nets -quiet $batch]
            dict incr metrics gather_ms [expr {[clock milliseconds]-$step}]
            set step [clock milliseconds]
            collect_routes $nets normal constants
            dict incr metrics preflight_ms [expr {[clock milliseconds]-$step}]
        }
        foreach name [dict keys $clocks] {if {[dict exists $normal $name]} {dict unset normal $name}}
        set normal_names [dict keys $normal]
        set ordinary_count [llength $normal_names]
        set batch_size [dict get $metrics batch_size]
        dict set metrics ordinary_nets $ordinary_count
        dict set metrics clock_aliases [dict size $clocks]
        dict set metrics physical_constant_required $constants
        dict set metrics ordinary_planned_calls [expr {($ordinary_count+$batch_size-1)/$batch_size}]
        dict set metrics discovery_ms [expr {[clock milliseconds]-$begin}]
        set step [clock milliseconds]
        set f [open $out/unroute.tsv w]; puts $f "net\taction"
        dict incr metrics output_ms [expr {[clock milliseconds]-$step}]
        # Do not materialize a list of every batch or convert native handles into
        # Tcl strings. Each chunk is resolved once and passed as that collection.
        for {set i 0} {$i < $ordinary_count} {incr i $batch_size} {
            dict set metrics stage ordinary_exact
            set batch [lrange $normal_names $i [expr {$i+$batch_size-1}]]
            dict incr metrics exact_native_queries
            set step [clock milliseconds]
            set objects [exact net $batch]
            dict incr metrics exact_ms [expr {[clock milliseconds]-$step}]
            dict set metrics max_native_collection_size [expr {max([dict get $metrics max_native_collection_size], [llength $objects])}]
            dict set metrics stage ordinary_unroute
            dict incr metrics ordinary_started_calls
            dict set metrics total_ms [expr {[clock milliseconds]-$begin}]
            cleanup_metrics_write $out $metrics
            set step [clock milliseconds]
            route_design -unroute -nets $objects
            dict incr metrics ordinary_unroute_ms [expr {[clock milliseconds]-$step}]
            dict incr metrics ordinary_completed_calls
            dict incr metrics ordinary_completed_nets [llength $batch]
            set step [clock milliseconds]
            foreach n $batch {puts $f "$n\tordinary_incident_net"}
            dict incr metrics output_ms [expr {[clock milliseconds]-$step}]
            unset objects
        }
        # Logical const aliases do not identify every physical VCC/GND branch.
        # Vivado exposes a device-wide physical-constant cleanup, not a site selector.
        if {$constants} {
            dict set metrics stage physical_constant
            dict incr metrics physical_constant_started_calls
            dict set metrics total_ms [expr {[clock milliseconds]-$begin}]
            cleanup_metrics_write $out $metrics
            set step [clock milliseconds]
            route_design -unroute -physical_nets
            dict incr metrics physical_constant_ms [expr {[clock milliseconds]-$step}]
            dict incr metrics physical_constant_completed_calls
            set step [clock milliseconds]
            puts $f "VCC_GND_PHYSICAL_NETS\tphysical_constant_cleanup"
            dict incr metrics output_ms [expr {[clock milliseconds]-$step}]
        }
        set step [clock milliseconds]
        foreach n [dict keys $clocks] {puts $f "$n\tclock_preserved"}
        close $f; set f {}
        dict incr metrics output_ms [expr {[clock milliseconds]-$step}]
        dict set metrics completed 1
        dict set metrics stage complete
    } message options]
    dict set metrics total_ms [expr {[clock milliseconds]-$begin}]
    if {$code} {
        if {$f ne ""} {catch {close $f}}
        dict set metrics error $message
        if {[dict exists $options -errorcode]} {dict set metrics errorcode [dict get $options -errorcode]}
        # Preserve the original native failure, including its error code and stack.
        catch {cleanup_metrics_write $out $metrics}
        return -options $options $message
    }
    cleanup_metrics_write $out $metrics
    return $metrics
}
proc plg::unplace {cell_names out allow_fixed} {
    file mkdir $out
    set objects [exact cell $cell_names]
    set f [open $out/unplaced.tsv w]; puts $f "cell\tloc\tbel\tloc_fixed\tbel_fixed\tpblock"
    foreach name [names $objects] loc [values LOC $objects] bel [values BEL $objects] lf [values IS_LOC_FIXED $objects] bf [values IS_BEL_FIXED $objects] pb [values PBLOCK $objects] {
        if {!$allow_fixed} {require [expr {$lf ni {1 true TRUE} && $bf ni {1 true TRUE}}] "Collateral cell is fixed: $name"}
        require [string match SLICE_* $loc] "Refusing to unplace non-Slice collateral: $name"
        puts $f [join [list $name $loc $bel $lf $bf $pb] \t]
    }
    close $f
    foreach batch [batches [names $objects]] {
        set cells [exact cell $batch]
        # unplace_cell removes LOC/BEL and their fixed flags. Setting a fixed
        # flag (even false) first can revalidate and reject the illegal old site.
        unplace_cell $cells
        foreach loc [values LOC $cells] {require [expr {$loc eq ""}] "Cell was not unplaced"}
        foreach flag [concat [values IS_LOC_FIXED $cells] [values IS_BEL_FIXED $cells]] {
            require [expr {$flag ni {1 true TRUE}}] "Unplaced cell remains fixed"
        }
    }
    # DONT_TOUCH, INIT, connectivity, control pins and Pblock membership are untouched.
}
proc plg::release {capture} {
    if {![dict size [dict get $capture ff]]} {return}
    set out [dict get $capture out]
    clean_sites [dict get $capture sites] $out/cleanup [dict get $capture old_nets]
    unplace [dict keys [dict get $capture ff]] $out/release 1
}
proc plg::parse_place {text} {
    set result [dict create placement_errors 0 invalid_routed_sites 0 illegal_sites {} routed_sites {}]
    foreach {key label} {unplaced {unplaced cells} site_errors {sites with errors}} {
        set pattern [format {# of %s[. ]*:[ ]*([0-9]+)} $label]
        require [regexp $pattern $text unused count] "Unrecognized report_place_status: missing $label"
        dict set result $key $count
    }
    foreach {key label} {placement_errors {sites with placement errors} invalid_routed_sites {sites with invalid routed sites}} {
        set pattern [format {# of %s[. ]*:[ ]*([0-9]+)} $label]
        if {[regexp $pattern $text unused count]} {dict set result $key $count}
    }
    set group {}
    foreach line [split $text \n] {
        set line [string trim $line]
        if {$line eq "Illegal Placement Sites"} {set group illegal_sites; continue}
        if {$line eq "Invalid Routed Sites"} {set group routed_sites; continue}
        if {$group ne "" && [regexp {^SLICE_X[0-9]+Y[0-9]+$} $line]} {dict lappend result $group $line}
    }
    foreach key {illegal_sites routed_sites} {dict set result $key [lsort -unique [dict get $result $key]]}
    require [expr {[dict get $result site_errors] == [dict get $result placement_errors]+[dict get $result invalid_routed_sites]}] "Unknown physical site error category"
    return $result
}
proc plg::status {out} {
    file mkdir $out
    report_place_status -file $out/place_status.rpt
    set f [open $out/place_status.rpt]; set text [read $f]; close $f
    set state [parse_place $text]
    set f [open $out/status.tcldict w]; puts $f $state; close $f
    return $state
}
proc plg::repair_sites {state out} {
    set sites [dict get $state illegal_sites]
    require [expr {[llength $sites] == [dict get $state placement_errors]}] "Illegal sites include unsupported resources; refusing broad cleanup"
    set cells [get_cells -of_objects [exact site $sites]]
    # Preflight all collateral locks before any routing or placement mutation.
    foreach name [names $cells] lf [values IS_LOC_FIXED $cells] bf [values IS_BEL_FIXED $cells] {
        require [expr {$lf ni {1 true TRUE} && $bf ni {1 true TRUE}}] "Illegal shared site includes fixed collateral: $name"
    }
    clean_sites $sites $out/cleanup
    unplace [names $cells] $out/release 0
}
proc plg::place {out args} {
    # Existing geometry remains the starting point. Only affected cells are
    # explicitly unplaced; the native placer may also move other movable cells.
    for {set pass 0} {$pass < 2} {incr pass} {
        place_design {*}$args
        set state [status $out/pass_$pass]
        require [expr {[dict get $state unplaced] == 0}] "Placement left unplaced cells"
        if {![dict get $state placement_errors]} {return $state}
        if {$pass == 0} {repair_sites $state $out/repair_0}
    }
    error "PHYSICAL_ECO: Illegal placement persists after one bounded shared-site repair; routing blocked"
}
proc plg::before_route {out} {
    set state [status $out/before]
    require [expr {[dict get $state unplaced] == 0 && [dict get $state placement_errors] == 0}] "Unplaced cells or illegal packing; routing blocked"
    if {[dict get $state invalid_routed_sites]} {
        set sites [dict get $state routed_sites]
        require [expr {[llength $sites] == [dict get $state invalid_routed_sites]}] "Unsupported invalid routed sites; routing blocked"
        clean_sites $sites $out/stale_routes
        set state [status $out/after_cleanup]
    }
    require [expr {[dict get $state unplaced] == 0 && [dict get $state site_errors] == 0}] "Physical status is not clean; routing blocked"
    set f [open $out/PASS w]; puts $f "All cells placed; no illegal or invalid routed sites"; close $f
    return $state
}
proc plg::check_route_report {text} {
    foreach {key label} {total {routable nets} routed {fully routed nets} errors {nets with routing errors}} {
        require [regexp [format {# of %s[. ]*:[ ]*([0-9]+)} $label] $text unused value] "Unrecognized route report: $label"
        set $key $value
    }
    # Vivado omits zero-valued unrouted-net rows in fully routed designs.
    set unrouted [expr {$total-$routed}]
    regexp {# of unrouted nets[. ]*:[ ]*([0-9]+)} $text unused unrouted
    require [expr {$total == $routed && $errors == 0 && $unrouted == 0}] "Final routing incomplete; this is a physical failure, not a timing annotation"
}
proc plg::assert_routed {out} {
    set state [status $out/placement]
    require [expr {[dict get $state unplaced] == 0 && [dict get $state site_errors] == 0}] "Final physical placement invalid"
    report_route_status -file $out/route_status.rpt
    set f [open $out/route_status.rpt]; set text [read $f]; close $f
    check_route_report $text
    set f [open $out/PASS w]; puts $f "Physical placement and complete routing PASS"; close $f
}
