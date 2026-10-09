# Case-isolated joint cone ECO. Functional equivalence is checked by construction.
namespace eval jc {}
proc jc::config {name} {
    set ref [sb::ref $name]; set init {}
    sb::require [regexp {^(LUT[1-6]|MUXF[78])$} $ref] "Unsupported combinational primitive $name $ref"
    if {[string match LUT* $ref]} {set init [string tolower [get_property INIT [sb::cell $name]]]}
    return [dict create ref $ref init $init]
}
proc jc::config_equal {a b} {
    if {[lsort [dict keys $a]] ne [lsort [dict keys $b]]} {return 0}
    dict for {key value} $a {if {$value ne [dict get $b $key]} {return 0}}
    return 1
}
proc jc::counts {} {
    set d [sb::counts]
    foreach ref {MUXF7 MUXF8} {dict set d $ref [llength [get_cells -hier -filter "IS_PRIMITIVE == 1 && REF_NAME == $ref"]]}
    return $d
}
proc jc::save {name value path} {set f [open $path w]; puts $f [list set $name $value]; close $f}
proc jc::origin {source spec} {
    set c [file dirname $source]
    if {[dict exists $spec clones $c]} {return "[dict get $spec clones $c original]/[file tail $source]"}
    return $source
}
proc jc::prepare {spec prior out} {
    set before {}; set expected {}; set configs {}; set old_inputs {}; set links [dict get $spec connections]
    set old_outputs {}; set targets [dict get $spec targets]; set ff_configs {}; set inherited {}
    # Verify inherited added logic and record its complete original pin functions.
    dict for {name item} [dict get $prior clones] {
        set cfg [jc::config $name]
        sb::require [expr {[dict get $cfg ref] eq [dict get $item config ref]}] "Inherited primitive type changed"
        if {[dict get $cfg init] ne {}} {sb::require [expr {[dict get $cfg init] eq [dict get $item config init]}] "Inherited LUT truth table changed"}
        dict set inherited $name [dict create config $cfg target [dict get $item target]]
        dict set configs $name $cfg
        foreach pin [sb::names [get_pins -of_objects [sb::cell $name] -filter {DIRECTION == IN}]] {dict set old_inputs $pin [sb::signal $pin]}
    }
    dict for {name item} [dict get $spec clones] {
        sb::require [expr {![llength [get_cells -quiet [list $name]]]}] "Clone name collision: $name"
        set c [dict get $item original]; set cfg [jc::config $c]
        sb::require [expr {[jc::config_equal $cfg [dict get $item config]]}] "Stale clone config $c"
        dict set configs $c $cfg
        foreach pin [sb::names [get_pins -of_objects [sb::cell $c] -filter {DIRECTION == IN}]] {
            set signal [sb::signal $pin]; dict set old_inputs $pin $signal
            set np "$name/[file tail $pin]"
            sb::require [dict exists $links $np] "Missing cloned input $np"
            set link [dict get $links $np]
            if {[dict get $link kind] eq "constant"} {
                sb::require [expr {$signal eq [list constant [dict get $link source]]}] "Constant equivalence failure $np"
            } else {
                sb::require [expr {$signal eq [list drivers [list [jc::origin [dict get $link source] $spec]]]}] "Input equivalence failure $np"
            }
        }
    }
    dict for {pin pair} [dict get $spec changes] {
        lassign $pair old new
        sb::require [expr {[sb::drivers $pin] eq [list $old]}] "Stale endpoint input $pin"
        sb::require [expr {[jc::origin $new $spec] eq $old}] "Replacement is not functionally equivalent: $pin"
        dict set links $pin [dict create kind driver source $new anchor $pin]
        dict set old_inputs $pin [list drivers [list $old]]
    }
    dict for {pin link} $links {
        if {[dict get $link kind] ne "driver"} {continue}
        set source [dict get $link source]
        if {![dict exists $expected $source]} {
            if {[dict exists $spec clones [file dirname $source]]} {set sinks {}} else {set sinks [sb::loads $source]; dict set before $source $sinks}
            dict set expected $source $sinks
        }
        dict lappend expected $source $pin
    }
    dict for {pin pair} [dict get $spec changes] {
        set old [lindex $pair 0]
        if {![dict exists $expected $old]} {set sinks [sb::loads $old]; dict set expected $old $sinks; dict set before $old $sinks}
        set sinks [dict get $expected $old]; set i [lsearch -exact $sinks $pin]
        sb::require [expr {$i>=0}] "Missing old load $pin"
        dict set expected $old [lreplace $sinks $i $i]
    }
    set bf [open $out/projected_fanout.tsv w]; puts $bf "driver\tbefore\tafter"
    set unlocknets {};set unlockroots {};set fake {};set index 0
    dict for {source sinks} $expected {
        sb::require [expr {[llength $sinks] == [llength [lsort -unique $sinks]] && [llength $sinks]<100}] "Fanout/duplicate load violation $source"
        dict set expected $source [lsort $sinks]
        sb::require [expr {[dict exists $spec projected $source] && [dict get $spec projected $source]==[llength $sinks]}] "Offline/native budget differs $source"
        set n 0
        if {[dict exists $before $source]} {
            set n [llength [dict get $before $source]]
            set nets [get_nets -segments -of_objects [sb::pin $source]]
            foreach net $nets {sb::require [expr {![sb::one_bit [get_property IS_ROUTE_FIXED $net]]}] "Fixed route $source"}
            dict set unlocknets $source [dict create kind ordinary signal [list drivers [list $source]] anchor $source]
            dict set unlockroots $source [dict create inputs {}]
            dict set fake u[incr index] [dict create key $source]
        }
        puts $bf "$source\t$n\t[llength $sinks]"
    }
    close $bf
    dict for {pin link} $links {
        if {[dict get $link kind] ne "constant"} {continue}
        set key [list constant [dict get $link source]]
        dict set unlocknets $key [dict create kind constant signal $key anchor [dict get $link anchor]]
        dict set unlockroots $key [dict create inputs {}]
        dict set fake u[incr index] [dict create key $key]
    }
    dict for {endpoint row} $targets {
        foreach c [lsort -unique [list [file dirname $endpoint] [dict get $row original]]] {
            dict set ff_configs $c [sb::config $c]
            foreach pin [sb::names [get_pins -of_objects [sb::cell $c] -filter {DIRECTION == IN}]] {dict set old_inputs $pin [sb::signal $pin]}
        }
    }
    return [dict create spec $spec before $before expected $expected connections $links configs $configs old_inputs $old_inputs ff_configs $ff_configs inherited $inherited counts_before [jc::counts] unlock [dict create snapshot [dict create nets $unlocknets roots $unlockroots] graph [dict create moves [dict get $spec changes] replicas $fake]]]
}
proc jc::augment {plan certificate} {
    set local [dict get $plan local_broadcast];set graph [dict get $local graph];set snapshot [dict get $local snapshot]
    array set expected [dict get $graph expected];array set nets [dict get $snapshot nets];array set inputs [dict get $graph new_inputs]
    array set before [dict get $certificate before]
    dict for {source sinks} [dict get $certificate expected] {
        if {[info exists expected($source)] && [info exists before($source)]} {sb::require [expr {[lsort $expected($source)] eq [lsort $before($source)]}] "Inherited output certificate mismatch $source"}
        set expected($source) $sinks
        if {![info exists nets($source)]} {set nets($source) [dict create kind ordinary signal [list drivers [list $source]] anchor $source before {}]}
    }
    dict for {pin link} [dict get $certificate connections] {
        if {[dict get $link kind] eq "constant"} {
            set key [list constant [dict get $link source]]
            if {![info exists nets($key)]} {set nets($key) [dict create kind constant signal $key anchor [dict get $link anchor] before {}]}
            set inputs($pin) $key
        } else {set inputs($pin) [dict get $link source]}
    }
    dict set graph expected [array get expected];dict set graph new_inputs [array get inputs];dict set snapshot nets [array get nets]
    dict set local graph $graph;dict set local snapshot $snapshot;dict set plan local_broadcast $local
    set added 0
    dict for {name item} [dict get $certificate spec clones] {if {[string match LUT* [dict get $item config ref]]} {incr added}}
    dict incr plan lut_added $added
    if {[dict exists $plan regional]} {dict set plan regional [jc::augment_regional [dict get $plan regional] $certificate]}
    return $plan
}
proc jc::verify {cert out placed} {
    file mkdir $out;sb::spatial_cache
    set expected_counts [dict get $cert counts_before]
    dict for {name item} [dict get $cert spec clones] {
        set ref [dict get $item config ref];dict incr expected_counts [expr {[string match LUT* $ref] ? "lut" : $ref}]
        sb::require [expr {[jc::config_equal [jc::config $name] [dict get $item config]]}] "Clone config mismatch $name"
        sb::require [sb::one_bit [get_property DONT_TOUCH [sb::cell $name]]] "Clone protection missing"
        sb::require [expr {![sb::one_bit [get_property IS_LOC_FIXED [sb::cell $name]]] && ![sb::one_bit [get_property IS_BEL_FIXED [sb::cell $name]]]}] "Clone exact location locked"
        if {$placed} {sb::require [expr {[dict get [sb::position $name] slr] eq [dict get $item target]}] "Clone SLR mismatch $name"}
    }
    sb::require [expr {[jc::counts] eq $expected_counts}] "Unexpected primitive-count change"
    dict for {c cfg} [dict get $cert configs] {sb::require [expr {[jc::config_equal [jc::config $c] $cfg]}] "Original/inherited primitive changed $c"}
    dict for {c cfg} [dict get $cert ff_configs] {sb::require [expr {[sb::config $c] eq $cfg}] "FF configuration changed $c"}
    dict for {pin signal} [dict get $cert old_inputs] {
        if {[dict exists $cert spec changes $pin]} {set signal [list drivers [list [lindex [dict get $cert spec changes $pin] 1]]]}
        sb::require [expr {[sb::signal $pin] eq $signal}] "Original/FF input changed $pin"
    }
    dict for {pin link} [dict get $cert connections] {
        set expected [expr {[dict get $link kind] eq "constant" ? [list constant [dict get $link source]] : [list drivers [list [dict get $link source]]]}]
        sb::require [expr {[sb::signal $pin] eq $expected}] "Exact new input mismatch $pin"
    }
    dict for {source sinks} [dict get $cert expected] {sb::require [expr {[sb::loads $source] eq $sinks}] "Exact output mismatch $source"}
    dict for {c item} [dict get $cert inherited] {
        sb::require [expr {![sb::one_bit [get_property IS_LOC_FIXED [sb::cell $c]]] && ![sb::one_bit [get_property IS_BEL_FIXED [sb::cell $c]]]}] "Inherited cone exact location locked"
        if {$placed} {sb::require [expr {[dict get [sb::position $c] slr] eq [dict get $item target]}] "Inherited cone SLR mismatch"}
    }
    set f [open $out/joint_structure.tsv w];puts $f "check\tvalue";puts $f "equivalent_clone_functions\tPASS\nall_modified_connections\tPASS\noriginal_FF_controls\tPASS\ninherited_cones\tPASS\nfanout_budget\tPASS\ncounts\tPASS\nplacement_checked\t$placed";close $f
}
proc jc::guard_pins {cert} {
    set guard {};set sources {}
    dict for {pin sinks} [dict get $cert before] {lappend sources [sb::pin $pin]}
    foreach batch [sb::chunks $sources 128] {
        foreach p [all_fanout -flat -endpoints_only -from $batch] {lappend guard [get_property NAME $p]}
    }
    dict for {c cfg} [dict get $cert ff_configs] {
        foreach p [get_pins -of_objects [sb::cell $c] -filter {REF_PIN_NAME == D || REF_PIN_NAME == CE || REF_PIN_NAME == R || REF_PIN_NAME == S}] {lappend guard [get_property NAME $p]}
        foreach p [all_fanout -flat -endpoints_only -from [sb::pin "$c/Q"]] {lappend guard [get_property NAME $p]}
    }
    foreach p [get_timing_paths -max_paths 1000 -nworst 1] {lappend guard [get_property ENDPOINT_PIN $p]}
    return [lsort -unique $guard]
}
proc jc::timing_object {name} {
    set p [get_pins -quiet [list $name]]
    if {![llength $p]} {set p [get_ports -quiet [list $name]]}
    sb::require [expr {[llength $p]==1}] "Missing timing object $name"
    return $p
}
proc jc::reports {cert pins out} {
    file mkdir $out
    set objects {};foreach p $pins {lappend objects [jc::timing_object $p]}
    set f [open $out/guard_slacks.tsv w];puts $f "endpoint\ttype\tslack\tstartpoint"
    foreach type {max min} {
        foreach p [get_timing_paths -to $objects -delay_type $type -max_paths [llength $pins] -nworst 1] {puts $f "[get_property ENDPOINT_PIN $p]\t$type\t[get_property SLACK $p]\t[get_property STARTPOINT_PIN $p]"}
    }
    close $f
    report_timing_summary -delay_type min_max -file $out/timing_summary.rpt
    report_route_status -file $out/route_status.rpt
    report_timing -max_paths 100 -nworst 1 -file $out/worst100.rpt
}
proc jc::apply {cert out {unroute 1}} {
    set spec [dict get $cert spec]
    set boundary [lb::unlock_boundaries [dict get $cert unlock]]
    if {$unroute && [llength [dict get $boundary unroute]]} {route_design -unroute -nets [get_nets [dict get $boundary unroute]]}
    set groups {};set manifest [open $out/added_cells.tsv w];puts $manifest "cell\toriginal\tref\ttarget"
    dict for {name item} [dict get $spec clones] {
        set cfg [dict get $item config]
        create_cell -reference [dict get $cfg ref] $name
        if {[dict get $cfg init] ne {}} {set_property INIT [dict get $cfg init] [sb::cell $name]}
        create_net ${name}_net
        connect_net -net [get_nets ${name}_net] -objects [sb::pin "$name/O"]
        dict lappend groups [dict get $item target] $name
        puts $manifest "$name\t[dict get $item original]\t[dict get $cfg ref]\t[dict get $item target]"
    }
    close $manifest
    dict for {pin pair} [dict get $spec changes] {disconnect_net -net [get_nets -of_objects [sb::pin $pin]] -pinlist [sb::pin $pin]}
    set ordinary {};set constants {}
    dict for {pin link} [dict get $cert connections] {
        if {[dict get $link kind] eq "constant"} {dict lappend constants [dict get $link anchor] $pin} else {dict lappend ordinary [dict get $link source] $pin}
    }
    foreach table {ordinary constants} {
        dict for {anchor pins} [set $table] {
            set objects {};foreach pin $pins {lappend objects [sb::pin $pin]}
            connect_net -hierarchical -net [get_nets -of_objects [sb::pin $anchor]] -objects $objects
        }
    }
    lb::restore_boundaries [dict get $boundary properties]
    dict for {slr names} $groups {
        set pb [get_pblocks -quiet localrep_$slr]
        if {![llength $pb]} {set pb [create_pblock localrep_$slr];resize_pblock $pb -add $slr;set_property EXCLUDE_PLACEMENT false $pb}
        set objects [get_cells $names]
        add_cells_to_pblock $pb $objects;set_property IS_SOFT false $pb
        set_property DONT_TOUCH true $objects
        set_property IS_LOC_FIXED false $objects;set_property IS_BEL_FIXED false $objects
        set_property DONT_TOUCH true [get_nets -segments -of_objects [get_pins -of_objects $objects -filter {DIRECTION == OUT}]]
    }
    sb::spatial_cache
}

proc jc::augment_regional {regional cert} {
    array set updates [dict get $cert expected]
    set roots {};set changes 0
    foreach root [dict get $regional roots] {
        set key [dict get $root driver]
        if {[info exists updates($key)]} {dict set root frontier $updates($key);incr changes}
        set nodes {};array set edges {}
        foreach node [dict get $root nodes] {
            set source [dict get $node name]/O
            if {[info exists updates($source)]} {dict set node loads $updates($source);incr changes}
            set edges([dict get $node name]/I0) [dict get $node loads]
            lappend nodes $node
        }
        dict set root nodes $nodes
        set pending [dict get $root frontier];set leaves {};set seen {}
        while {[llength $pending]} {
            set next {}
            foreach p $pending {
                sb::require [expr {![dict exists $seen $p]}] "Regional cycle/duplicate after augmentation"
                dict set seen $p 1
                if {[info exists edges($p)]} {lappend next {*}$edges($p)} else {lappend leaves $p}
            }
            set pending $next
        }
        dict set root sinks [lsort $leaves]
        lappend roots $root
        array unset edges *
    }
    dict set regional roots $roots
    rf::configure [dict get $regional config]
    foreach root $roots {rf::validate_tree $root}
    puts "JOINT_REGIONAL_CERTIFICATE updated_sources=$changes; complete tree coverage retained"
    return $regional
}
