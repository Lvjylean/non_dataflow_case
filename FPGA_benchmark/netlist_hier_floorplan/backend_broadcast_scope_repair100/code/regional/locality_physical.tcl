# Regional-only extension. Seed/base use the unchanged physical contract.
proc plg::capture {pins out} {
    file mkdir $out
    set ff {}; set sites {}; set old_nets {}
    foreach batch [batches [lsort -unique $pins]] {
        set objects [exact pin $batch]
        set expanded [expr {[info exists ::env(BL_LOCALITY)] && $::env(BL_LOCALITY) eq "1"}]
        if {$expanded} {set dp [filter $objects {DIRECTION == IN && IS_CLOCK == 0}]} \
        else {set dp [filter $objects {DIRECTION == IN && REF_PIN_NAME == D}]}
        if {![llength $dp]} {continue}
        foreach name [names [get_nets -quiet -segments -of_objects $dp]] {dict set old_nets $name 1}
        if {$expanded} {
            set cells [get_cells -of_objects $dp -filter {REF_NAME =~ FD* || REF_NAME =~ LUT* || REF_NAME =~ MUXF*}]
        } else {set cells [get_cells -of_objects $dp -filter {REF_NAME =~ FD*}]}
        foreach name [names $cells] loc [values LOC $cells] bel [values BEL $cells] {
            if {$loc eq ""} {continue}
            require [string match SLICE_* $loc] "Modified placed CLB cell is outside a Slice: $name ($loc)"
            if {$expanded && ![string match f96_identity_* $name] && ![string match sbeco_* $name]} {
                set obj [exact cell [list $name]]
                require [expr {![sb::one_bit [get_property IS_LOC_FIXED $obj]] && ![sb::one_bit [get_property IS_BEL_FIXED $obj]]}] "Fixed original cell cannot be released by locality ECO: $name"
            }
            dict set ff $name [list $loc $bel]
            dict set sites $loc 1
        }
    }
    set f [open $out/changed_ff.tsv w]; puts $f "cell\told_loc\told_bel"
    dict for {name pos} $ff {puts $f [join [linsert $pos 0 $name] \t]}
    close $f
    return [dict create ff $ff sites [dict keys $sites] old_nets [dict keys $old_nets] out $out]
}
