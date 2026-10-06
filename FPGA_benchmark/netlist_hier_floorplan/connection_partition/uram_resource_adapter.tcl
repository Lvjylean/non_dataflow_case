# Resource-specific additions preserve cell ownership and all base soft ranges.
proc bi_uram_extra {mid} {
    if {![info exists ::bi_resource_extra_crs] || ![dict exists $::bi_resource_extra_crs $mid URAM]} {return {}}
    return [dict get $::bi_resource_extra_crs $mid URAM]
}

proc bi_expected_sites {mid} {
    set filter {NAME =~ SLICE_* || NAME =~ DSP48E2_* || NAME =~ RAMB18_* || NAME =~ RAMB36_* || NAME =~ URAM288_*}
    set wanted [f96::values NAME [get_sites -of_objects [get_clock_regions [dict get $::planned_regions $mid]] -filter $filter]]
    set extra [bi_uram_extra $mid]
    if {[llength $extra]} {
        lappend wanted {*}[f96::values NAME [get_sites -of_objects [get_clock_regions $extra] -filter {NAME =~ URAM288_*}]]
    }
    return [lsort -unique $wanted]
}

proc bi_cell_inside_soft {mid ref cr} {
    if {$cr in [dict get $::planned_regions $mid]} {return 1}
    return [expr {[string match URAM288* $ref] && $cr in [bi_uram_extra $mid]}]
}

proc bi_apply_resource_extensions {out} {
    set f [open $out/uram_soft_binding.tsv w]
    puts $f "module\tresource\tadded_clock_regions\tadded_sites\tsite_names"
    dict for {mid resources} $::bi_resource_extra_crs {
        if {[dict keys $resources] ne {URAM}} {error "Unsupported resource-specific extension: $mid"}
        set crs [bi_uram_extra $mid]
        set sites [lsort -unique [f96::values NAME [get_sites -of_objects [get_clock_regions $crs] -filter {NAME =~ URAM288_*}]]]
        if {![llength $sites]} {error "No URAM sites in requested extension: $mid"}
        set pb [get_pblocks hfp_$mid]
        foreach site $sites {resize_pblock $pb -add ${site}:${site}}
        if {![get_property IS_SOFT $pb]} {error "Resource extension requires a soft Pblock"}
        puts $f "$mid\tURAM\t[join $crs ,]\t[llength $sites]\t[join $sites ,]"
    }
    close $f
}

# Keep the original strict member and exact-site checks with a per-resource target.
proc bi_geometry {out {require_all 0}} {
    file mkdir $out
    array set good {}; array set bad {}
    set f [open $out/binding_mismatches.tsv w]; puts $f "cell\texpected\tactual"
    set cells [get_cells -hier -filter {IS_PRIMITIVE == 1}]
    foreach name [f96::values NAME $cells] pb [f96::values PBLOCK $cells] {
        if {![info exists ::cf_owner($name)]} {continue}
        set mid $::cf_owner($name)
        if {![dict exists $::planned_regions $mid]} {continue}
        if {$pb eq "hfp_$mid"} {incr good($mid)} else {incr bad($mid); puts $f "$name\thfp_$mid\t$pb"}
    }
    close $f
    set failures 0
    set f [open $out/binding.tsv w]
    puts $f "module\toriginal\tretained_matching\tretained_mismatch\tabsent_original_names\tsoft"
    set g [open $out/site_geometry.tsv w]; puts $g "module\texpected_sites\tactual_sites\texact_match\tparent"
    set filter {NAME =~ SLICE_* || NAME =~ DSP48E2_* || NAME =~ RAMB18_* || NAME =~ RAMB36_* || NAME =~ URAM288_*}
    dict for {mid crs} $::planned_regions {
        foreach a {good bad} {if {![info exists ${a}($mid)]} {set ${a}($mid) 0}}
        set expected [llength $::cf_members($mid)]
        set absent [expr {$expected-$good($mid)-$bad($mid)}]
        set pb [get_pblocks hfp_$mid]; set soft [get_property IS_SOFT $pb]
        puts $f "$mid\t$expected\t$good($mid)\t$bad($mid)\t$absent\t$soft"
        set wanted [bi_expected_sites $mid]
        set actual [lsort -unique [f96::values NAME [get_sites -of_objects $pb -filter $filter]]]
        set exact [expr {$wanted eq $actual}]
        puts $g "$mid\t[llength $wanted]\t[llength $actual]\t$exact\t[get_property PARENT $pb]"
        if {$bad($mid) || !$soft || !$exact || ($require_all && $absent)} {incr failures}
    }
    close $f;close $g
    return $failures
}
