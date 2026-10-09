# Bounded physical repair only; no functional edits or persistent exact locks.
namespace eval scr {variable max_cells 32; variable max_trials 64}
proc scr::xy {site} {
    if {![regexp {^SLICE_X([0-9]+)Y([0-9]+)$} $site unused x y]} {error "Unsupported repair site: $site"}
    return [list $x $y]
}
proc scr::scan {plan out} {
    file mkdir $out
    set f [open $out/scope.tsv w]
    puts $f "cell\ttarget_slr\tactual_slr\tloc\tbel\tstatus"
    set failed {}
    dict for {name item} [dict get $plan local_broadcast graph replicas] {
        set c [sb::cell $name];set loc [get_property LOC $c]
        set target [dict get $item slr];set actual ""
        if {$loc ne ""} {set actual [sb::names [get_slrs -of_objects [get_sites -of_objects $c]]]}
        set ok [expr {$actual eq $target}]
        puts $f [join [list $name $target $actual $loc [get_property BEL $c] [expr {$ok ? "PASS" : "FAIL"}]] \t]
        if {!$ok} {dict set failed $name [dict create target $target actual $actual loc $loc bel [get_property BEL $c]]}
    }
    close $f
    return $failed
}
proc scr::candidate_sites {pb oldloc} {
    lassign [xy $oldloc] x y
    set scored {}
    foreach site [sb::names [get_sites -of_objects $pb -filter {SITE_TYPE == SLICEL || SITE_TYPE == SLICEM}]] {
        lassign [xy $site] sx sy
        lappend scored [list [expr {abs($sx-$x)+abs($sy-$y)}] $site]
    }
    return [lsort -integer -index 0 $scored]
}
proc scr::preflight {failed} {
    variable max_cells
    sb::require [expr {[dict size $failed] <= $max_cells}] "Scope repair exceeds bounded cell budget"
    dict for {name item} $failed {
        set c [sb::cell $name];set target [dict get $item target]
        # Whole-cone MUX relocation needs a separate certificate, not this repair.
        sb::require [expr {[sb::ref $name] in {FDRE FDSE}}] "Scope repair supports only independent FF replicas: $name"
        xy [dict get $item loc]
        sb::require [expr {![sb::one_bit [get_property IS_LOC_FIXED $c]] && ![sb::one_bit [get_property IS_BEL_FIXED $c]]}] "Scope outlier has an explicit lock: $name"
        foreach prop {RLOC RPM MACRO_NAME} {
            sb::require [expr {[get_property $prop $c] eq ""}] "Scope outlier is part of a relative macro: $name"
        }
        set pb [get_pblocks -quiet localrep_$target]
        sb::require [expr {[llength $pb] == 1 && ![sb::one_bit [get_property IS_SOFT $pb]] && [get_property PBLOCK $c] eq "localrep_$target"}] "Scope repair requires the existing direct hard SLR Pblock: $name"
        set slrs [sb::names [get_slrs -of_objects [get_sites -of_objects $pb]]]
        sb::require [expr {$slrs eq $target}] "Scope Pblock spans an unexpected SLR: $name"
    }
}
proc scr::repair {plan out} {
    variable max_trials
    set failed [scan $plan $out/before]
    if {![dict size $failed]} {
        set f [open $out/PASS w];puts $f "No scope outliers; no placement or routing mutation";close $f
        return $plan
    }
    preflight $failed
    set names [dict keys $failed];set sites {};set shared {}
    dict for {name item} $failed {lappend sites [dict get $item loc]}
    # Preserve the original D-LUT and all other occupants of the old sites.
    foreach c [get_cells -of_objects [plg::exact site [lsort -unique $sites]]] {
        set n [get_property NAME $c]
        if {[lsearch -exact $names $n] < 0} {dict set shared $n [list [get_property LOC $c] [get_property BEL $c]]}
    }
    puts "SCOPE_REPAIR begin cells=[llength $names] shared=[dict size $shared]";flush stdout
    # Clean incident site routes, including physical constants; preserve clocks.
    plg::clean_sites $sites $out/cleanup
    plg::unplace $names $out/release 0
    set f [open $out/moves.tsv w];puts $f "cell\told_loc\tnew_loc\tnew_bel\ttarget_slr\ttrials"
    set errors [open $out/candidate_errors.tsv w];puts $errors "cell\tsite\terror"
    set code [catch {
        dict for {name item} $failed {
            set target [dict get $item target];set c [sb::cell $name]
            set trials 0;set placed 0
            foreach score [candidate_sites [get_pblocks localrep_$target] [dict get $item loc]] {
                set site [lindex $score 1]
                # Empty sites avoid disturbing or repacking existing control sets.
                if {[llength [get_cells -quiet -of_objects [get_sites $site]]]} {continue}
                if {[incr trials] > $max_trials} {break}
                if {[catch {place_cell [list $name $site]} message]} {
                    puts $errors [join [list $name $site [string map [list \n " " \t " "] $message]] \t]
                    if {[get_property LOC $c] ne ""} {unplace_cell $c}
                    continue
                }
                sb::require [expr {[sb::names [get_slrs -of_objects [get_sites -of_objects $c]]] eq $target}] "Native local assignment escaped target SLR: $name"
                puts $f [join [list $name [dict get $item loc] [get_property LOC $c] [get_property BEL $c] $target $trials] \t]
                set placed 1;break
            }
            sb::require $placed "No native-legal empty site within scope repair budget: $name"
        }
    } message options]
    close $f;close $errors
    # place_cell fixes placements. Remove temporary locks before STA/routing.
    foreach name $names {
        set c [sb::cell $name]
        if {[get_property LOC $c] ne ""} {
            set_property IS_LOC_FIXED false $c
            set_property IS_BEL_FIXED false $c
        }
    }
    if {$code} {
        write_checkpoint -force $out/failed_repair.dcp
        return -options $options $message
    }
    set remaining [scan $plan $out/after]
    sb::require [expr {![dict size $remaining]}] "Scope repair left outliers"
    dict for {name pos} $shared {
        set c [sb::cell $name]
        sb::require [expr {[list [get_property LOC $c] [get_property BEL $c]] eq $pos}] "Local scope repair disturbed shared-site geometry: $name"
    }
    set state [plg::status $out/physical]
    sb::require [expr {[dict get $state unplaced] == 0 && [dict get $state placement_errors] == 0}] "Local scope repair has unplaced cells or illegal packing"
    dict set plan scope_repair [dict create method native_empty_site_local_assignment moved $names count [llength $names] persistent_exact_locks 0 shared_site_cells_preserved [dict size $shared]]
    set f [open $out/PASS w];puts $f "All replica scopes legal; temporary locks released; shared-site placement preserved";close $f
    puts "SCOPE_REPAIR complete cells=[llength $names]";flush stdout
    return $plan
}
