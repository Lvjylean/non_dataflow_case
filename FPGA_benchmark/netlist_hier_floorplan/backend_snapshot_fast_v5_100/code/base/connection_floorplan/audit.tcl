proc cf_values {property objects} {
    if {![llength $objects]} {return {}}
    set values [get_property $property $objects]
    if {[llength $objects] == 1} {return [list $values]}
    return $values
}

proc cf_binding_audit {directory} {
    global planned_regions
    file mkdir $directory
    # Native PBLOCK includes inherited assignments after hierarchy promotion.
    # Avoid a large repeatedly shared Tcl dictionary for all primitive names.
    set cells [get_cells -quiet [array names ::cf_owner]]
    if {[llength $cells] != [array size ::cf_owner]} {error "Original inventory not found"}
    array set bound {}; array set missing {}; array set extra {}
    set mismatch [open $directory/binding_mismatches.tsv w]
    puts $mismatch "cell\texpected\tactual"
    foreach name [cf_values NAME $cells] pb [cf_values PBLOCK $cells] {
        set expected $::cf_owner($name)
        if {![dict exists $planned_regions $expected]} {continue}
        set actual [string range $pb 4 end]
        set primary [expr {$actual eq "DSP_CHILD" ? $::cf_large : $actual}]
        if {$primary eq $expected} {
            incr bound($expected)
        } else {
            incr missing($expected)
            if {$primary ne ""} {incr extra($primary)}
            puts $mismatch "$name\t$expected\t$actual"
        }
        set expected_child [expr {$expected eq $::cf_large && $::cf_resource($name) eq "DSP"}]
        if {$expected_child && $actual eq "DSP_CHILD"} {incr bound(DSP_CHILD)}
        if {$expected_child && $actual ne "DSP_CHILD"} {incr missing(DSP_CHILD)}
        if {!$expected_child && $actual eq "DSP_CHILD"} {incr extra(DSP_CHILD)}
    }
    close $mismatch
    set failures 0
    set f [open $directory/binding.tsv w]
    puts $f "module\texpected\tbound\tmissing\textra\tsoft\tdirect_objects\tmethod"
    dict for {mid crs} $planned_regions {
        foreach var {bound missing extra} {if {![info exists ${var}($mid)]} {set ${var}($mid) 0}}
        set pb [get_pblocks hfp_$mid]
        set soft [get_property IS_SOFT $pb]
        puts $f "$mid\t[llength $::cf_members($mid)]\t$bound($mid)\t$missing($mid)\t$extra($mid)\t$soft\t[llength [get_cells -quiet -of_objects $pb]]\tNATIVE_PBLOCK"
        if {$missing($mid) || $extra($mid) || !$soft} {incr failures}
    }
    close $f
    set actual_sites [get_sites -of_objects [get_pblocks hfp_DSP_CHILD] -filter {NAME =~ DSP48E2_X*}]
    set expected_sites [get_sites -of_objects [get_clock_regions [dict get $planned_regions DSP_CHILD]] -filter {NAME =~ DSP48E2_X*}]
    set f [open $directory/dsp_geometry.tsv w]
    set same [expr {[lsort [cf_values NAME $actual_sites]] eq [lsort [cf_values NAME $expected_sites]]}]
    puts $f "expected_sites\tactual_sites\texact_match"
    puts $f "[llength $expected_sites]\t[llength $actual_sites]\t$same"
    close $f
    if {!$same} {incr failures}
    if {$failures} {error "Primitive binding or DSP geometry failed: $failures"}
}

proc cf_origin_candidates {name hint} {
    if {$hint eq ""} {return {}}
    set slash [string last / $name]
    set parent [expr {$slash >= 0 ? [string range $name 0 $slash] : ""}]
    return [lsort -unique [list $hint "$parent$hint"]]
}

proc cf_audit_regions {directory} {
    global planned_regions
    file mkdir $directory
    array set site_cr {}; array set cr_slr {}
    foreach cr [get_clock_regions] {
        set name [get_property NAME $cr]
        set cr_slr($name) [get_property NAME [get_slrs -of_objects $cr]]
        foreach site [cf_values NAME [get_sites -of_objects $cr]] {set site_cr($site) $name}
    }
    set cells [get_cells -hier -filter {IS_PRIMITIVE == 1}]
    set names [cf_values NAME $cells]; set refs [cf_values REF_NAME $cells]
    set locs [cf_values LOC $cells]; set hints [cf_values ORIG_CELL_NAME $cells]
    set pblocks [cf_values PBLOCK $cells]
    array set primitive {}
    foreach name $names {set primitive($name) 1}
    set counts [dict create]; set inside [dict create]; set provenance [dict create]
    array unset ::cf_live_origin; array set ::cf_live_origin {}
    set unf [open $directory/unassigned_cells.tsv w]; puts $unf "cell\tref\thint"
    array set exact {}; set missing [dict create]
    array set replicas {}
    foreach name $names ref $refs loc $locs hint $hints pb $pblocks {
        if {$ref in {VCC GND}} {continue}
        set ancestor $name; set nested 0
        while {[set slash [string last / $ancestor]] >= 0} {
            set ancestor [string range $ancestor 0 [expr {$slash-1}]]
            if {[info exists primitive($ancestor)]} {set nested 1; break}
        }
        if {$nested} {continue}
        set mid UNKNOWN; set origin ""; set method UNRESOLVED
        if {[info exists ::cf_owner($name)]} {
            set mid $::cf_owner($name); set origin $name; set method EXACT
            set exact($name) 1
        } else {
            set candidates {}
            foreach candidate [cf_origin_candidates $name $hint] {
                if {[info exists ::cf_owner($candidate)]} {lappend candidates $candidate}
            }
            if {[llength $candidates] > 1} {
                set native_candidates {}
                foreach candidate $candidates {
                    if {![info exists replicas($candidate)]} {
                        set seed [get_cells -quiet [list $candidate]]
                        set replicas($candidate) {}
                        if {[llength $seed]} {set replicas($candidate) [cf_values NAME [get_cells -quiet -include_replicated_objects $seed]]}
                    }
                    if {$name in $replicas($candidate)} {lappend native_candidates $candidate}
                }
                set candidates $native_candidates
            }
            if {[llength $candidates] == 1} {
                set origin [lindex $candidates 0]
                set mid $::cf_owner($origin); set method ORIGIN_METADATA_NATIVE_DISAMBIGUATED
            }
            if {$origin eq "" && [string match hfp_* $pb]} {
                set candidate [string range $pb 4 end]
                if {$candidate eq "DSP_CHILD"} {set candidate $::cf_large}
                if {[dict exists $planned_regions $candidate]} {
                    set mid $candidate; set method NATIVE_PBLOCK_NO_UNIQUE_ORIGIN
                }
            }
        }
        if {$origin ne ""} {set ::cf_live_origin($name) $origin}
        if {[string match hfg_identity_* $name] || [string match f96_identity_* $name]} {set mid FANOUT_HELPER; set method INSERTED}
        dict incr provenance [list $mid $method]
        if {![dict exists $planned_regions $mid]} {
            if {$mid eq "UNKNOWN"} {puts $unf "$name\t$ref\t$hint"}
            continue
        }
        set cr UNLOCATED; set slr UNLOCATED
        if {[info exists site_cr($loc)]} {set cr $site_cr($loc); set slr $cr_slr($cr)}
        dict incr counts [list $mid $slr $cr $ref]
        dict incr inside [list $mid [expr {$cr in [dict get $planned_regions $mid] ? "INSIDE" : "OUTSIDE"}]]
        if {$mid eq $::cf_large && $ref eq "DSP48E2"} {
            dict incr counts [list DSP_CHILD $slr $cr $ref]
            dict incr inside [list DSP_CHILD [expr {$cr in [dict get $planned_regions DSP_CHILD] ? "INSIDE" : "OUTSIDE"}]]
        }
    }
    close $unf
    foreach name [array names ::cf_owner] {
        set mid $::cf_owner($name)
        if {[dict exists $planned_regions $mid] && ![info exists exact($name)]} {dict incr missing $mid}
    }
    set f [open $directory/original_names_absent.tsv w]; puts $f "module\tabsent_original_names"
    dict for {mid count} $missing {puts $f "$mid\t$count"}; close $f
    foreach {filename header data} [list module_cr_primitive_counts.tsv "module\tslr\tcr\tref\tcount" $counts soft_region_spill.tsv "module\tstatus\tlogical_primitives" $inside ownership_provenance.tsv "module\tmethod\tcount" $provenance] {
        set f [open $directory/$filename w]; puts $f $header
        dict for {key value} $data {puts $f "[join $key \t]\t$value"}
        close $f
    }
    set f [open $directory/pblocks.tsv w]
    puts $f "pblock\tis_soft\tparent\tgrid_ranges\tassigned_count"
    foreach pb [get_pblocks hfp_*] {
        puts $f "$pb\t[get_property IS_SOFT $pb]\t[get_property PARENT $pb]\t[get_property GRID_RANGES $pb]\t[llength [get_cells -quiet -of_objects $pb]]"
    }
    close $f
}

proc cf_general_fanout {directory application} {
    set f [open $application r]; gets $f header
    set targets [dict create]
    while {[gets $f line] >= 0} {dict set targets [lindex [split $line \t] 0] 1}
    close $f
    set groups [dict create]
    foreach name [array names ::cf_live_origin] {
        set origin $::cf_live_origin($name)
        if {[dict exists $targets $origin]} {dict lappend groups $origin $name}
    }
    set f [open $directory/general_fanout_branches.tsv w]
    puts $f "target\tcell\toutput\tlogical\tphysical\tlimit\tresult"
    set failures 0; set checked 0; set missing 0; set maxlog 0; set maxphy 0
    set sf [open $directory/general_fanout_targets.tsv w]
    puts $sf "target\tassociated_live_cells\tassociation"
    dict for {target unused} $targets {
        set seed [get_cells -quiet [list $target]]
        if {[llength $seed] == 1} {
            set group [cf_values NAME [get_cells -quiet -include_replicated_objects $seed]]
            set association NATIVE_REPLICATED_OBJECTS
        } elseif {[dict exists $groups $target]} {
            set group [dict get $groups $target]
            set association ORIGIN_METADATA_REMOVED_SEED
        } else {
            incr missing; puts $sf "$target\t0\tUNRESOLVED"; continue
        }
        puts $sf "$target\t[llength $group]\t$association"
        set pins [get_pins -of_objects [get_cells -quiet $group] -filter {DIRECTION == OUT}]
        foreach pin $pins {
            set sinks [hfg::loads $pin]; set logical [llength $sinks]
            set segments [get_nets -quiet -segments -of_objects $pin]
            set physical [expr {max([unique_site_input_count $segments],[unique_site_input_count $sinks])}]
            set result [expr {$logical <= 512 && $physical <= 512 ? "PASS" : "FAIL"}]
            if {$result eq "FAIL"} {incr failures}
            incr checked; set maxlog [expr {max($maxlog,$logical)}]; set maxphy [expr {max($maxphy,$physical)}]
            set name [get_property NAME [get_cells -of_objects $pin]]
            puts $f "$target\t$name\t$pin\t$logical\t$physical\t512\t$result"
        }
        flush $f
    }
    close $f; close $sf
    set f [open $directory/general_fanout_summary.tsv w]
    puts $f "targets\tunresolved_targets\toutputs\tfailures\tmax_logical\tmax_physical\tequivalence"
    puts $f "[dict size $targets]\t$missing\t$checked\t$failures\t$maxlog\t$maxphy\tNOT_PROVED_BY_THIS_FANOUT_AUDIT"
    close $f
    if {$missing || $failures} {error "General 512 fanout gate: unresolved=$missing failures=$failures"}
}
