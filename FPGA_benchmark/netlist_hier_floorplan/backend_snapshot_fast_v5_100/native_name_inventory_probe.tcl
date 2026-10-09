# Read-only validation: OLD_CODE NEW_CODE DCP NEW_OUT fixture|large_prefix.
# Large mode validates the complete native/name index and parent grouping,
# plus sampled pin incidence. Full graph equivalence runs on native fixtures.
proc probe_phase {label} {
    set f [open $::out/phase.txt w];puts $f "[clock seconds]\t$label";close $f
    puts "PROBE_PHASE [clock seconds] $label";flush stdout
}
proc probe_full_cache {} {
    set objects [get_cells -quiet -hier -filter {IS_PRIMITIVE == 1}]
    sb::require [expr {[llength $objects] >= $::vs::property_limit}] "Insufficient fixture cells to saturate native cache"
    set objects [lrange $objects 0 [expr {$::vs::property_limit-1}]]
    sb::values NAME $objects
    sb::require [expr {[array size ::vs::properties] == $::vs::property_limit}] "Native cache was not saturated"
}
proc probe_file {path} {
    set f [open $path];set result [read $f];close $f
    return [lsort [split [string trimright $result \n] \n]]
}
if {[catch {
    lassign $argv old new checkpoint out mode
    if {$mode ni {fixture large_prefix}} {error "Expected fixture or large_prefix mode"}
    if {[file exists $out]} {error "Refusing existing validation output"}
    file mkdir $out
    set sha_before [lindex [exec sha256sum $checkpoint] 0]
    foreach f {core.tcl regional.tcl locality_inventory.tcl} {source $old/code/regional/$f}
    rename locality_inventory::capture locality_inventory::capture_original
    foreach f {core.tcl locality_inventory.tcl} {source $new/code/regional/$f}
    probe_phase open_checkpoint
    open_checkpoint $checkpoint
    set metrics [open $out/metrics.tsv w];puts $metrics "phase\telapsed_us\tcount"
    if {$mode eq "fixture"} {
        set ::vs::property_limit [expr {min(64,[llength [get_cells -quiet -hier -filter {IS_PRIMITIVE == 1}]])}]
        probe_phase native_fixture_original
        set original [vs::with original_full_cache {
            probe_full_cache
            locality_inventory::capture_original $out/original reference
        }]
        vs::save $::vs::last_statistics $out/original_cache.tsv
        foreach profile {batch reference} {
            probe_phase native_fixture_$profile
            set result [vs::with repaired_full_cache {
                probe_full_cache
                locality_inventory::capture $out/$profile $profile
            }]
            vs::save $::vs::last_statistics $out/${profile}_cache.tsv
            sb::require [expr {[dict get $result acquisition_profile] eq $profile}] "Unexpected native fallback"
            foreach file {cells edges diagnostics reuse_nets} {
                sb::require [expr {[probe_file $out/original/$file.tsv] eq [probe_file $out/$profile/$file.tsv]}] "Complete native graph mismatch: $file"
            }
            foreach key {schema status cells editable_cells nets edges constant_edges clock_nets fixed_nets disconnected_inputs diagnostics semantics} {
                sb::require [expr {[dict get $original $key] eq [dict get $result $key]}] "Native metadata mismatch: $key"
            }
        }
        set summary [dict create complete_native_graph_equivalence true cells [dict get $original cells] nets [dict get $original nets] edges [dict get $original edges]]
    } else {
        # Keep the actual production prefix and all its guards, stopping before
        # edge enumeration. No replacement native/property mocks are used.
        set body [info body locality_inventory::capture]
        set marker "    unset all_nets top_objects\n"
        set position [string first $marker $body]
        sb::require [expr {$position >= 0}] "Missing production prefix boundary"
        set body [string range $body 0 [expr {$position-1}]]
        append body {
            sb::require [expr {$profile eq "batch"}] "Real-case parent grouping fell back"
            sb::require [expr {[array size ::vs::properties] == $::vs::property_limit}] "Real-case cache no longer full"
            probe_phase complete_canonical_name_equivalence
            set expected [lsort -unique [get_property NAME $top_objects]]
            sb::require [expr {$roots eq $expected}] "Complete canonical name mismatch"
            unset expected
            set tick [clock microseconds]
            set name_batches [sb::name_chunks $roots 2048]
            set chunk_us [expr {[clock microseconds]-$tick}]
            puts $::metrics "standard_name_chunks\t$chunk_us\t[llength $roots]";flush $::metrics
            set flat {};foreach names $name_batches {lappend flat {*}$names}
            sb::require [expr {$flat eq $roots}] "Complete ordered name chunks mismatch"
            unset flat
            probe_phase complete_retained_handle_equivalence
            set tick [clock microseconds];set retained 0
            foreach names $name_batches {
                set handles {};foreach name $names {lappend handles $canonical_objects($name)}
                sb::require [expr {[sb::names $handles] eq $names}] "Retained canonical object mismatch"
                incr retained [llength $handles]
            }
            sb::require [expr {$retained == [llength $roots]}] "Retained canonical count mismatch"
            puts $::metrics "retained_handle_equivalence\t[expr {[clock microseconds]-$tick}]\t$retained";flush $::metrics
            probe_phase native_collection_and_name_sample_checks
            set count [llength $roots];set samples {}
            foreach fraction {0 1 2 3 4 5 6 7 8 9 10 11} {
                lappend samples [::tcl::lindex $roots [expr {($count-1)*$fraction/11}]]
            }
            set alias_names [array names extra_segments]
            lappend samples {*}[::tcl::lrange $alias_names 0 31]
            set samples [lsort -unique $samples]
            foreach root $samples {
                set object $canonical_objects($root)
                set retained_segments [list $object]
                if {[info exists extra_segments($root)]} {lappend retained_segments {*}$extra_segments($root)}
                set native_segments [get_nets -quiet -segments $object]
                sb::require [expr {[lsort [sb::names $retained_segments]] eq [lsort [sb::names $native_segments]]}] "Native segment group mismatch: $root"
                set filter {IS_LEAF == 1 && (DIRECTION == OUT || IS_CLOCK == 0)}
                sb::require [expr {[lsort [sb::names [get_pins -quiet -of_objects $retained_segments -filter $filter]]] eq [lsort [sb::names [get_pins -quiet -of_objects $native_segments -filter $filter]]]}] "Native pin incidence mismatch: $root"
            }
            set native_count 0
            foreach native_batch [sb::chunks $top_objects 2048] {incr native_count [llength $native_batch]}
            sb::require [expr {$native_count == [llength $top_objects] && $native_count > 500}] "Native collection chunking lost objects"
            foreach offset [list 0 [expr {$count/2}] [expr {$count-2048}]] {
                set tick [clock microseconds];set old [lrange $roots $offset [expr {$offset+2047}]]
                puts $::metrics "vivado_lrange_$offset\t[expr {[clock microseconds]-$tick}]\t[llength $old]";flush $::metrics
                set tick [clock microseconds];set fast [::tcl::lrange $roots $offset [expr {$offset+2047}]]
                puts $::metrics "tcl_lrange_$offset\t[expr {[clock microseconds]-$tick}]\t[llength $fast]";flush $::metrics
                sb::require [expr {$old eq $fast}] "Native wrapper and standard name slice differ"
            }
            foreach stream [list $runtime $diag $edges $reuse_nets] {close $stream}
            return [dict create complete_canonical_index true native_collection_count $native_count names $count name_batches [llength $name_batches] name_chunk_us $chunk_us parent_alias_groups [array size extra_segments] sampled_segment_and_pin_groups [llength $samples] full_real_graph_comparison false]
        }
        proc locality_inventory::probe_prefix {out {profile {}}} $body
        probe_phase real_prefix_full_cache
        set tick [clock microseconds]
        set summary [vs::with locality_candidate_reads {
            probe_full_cache
            locality_inventory::probe_prefix $out/prefix batch
        }]
        dict set summary prefix_and_validation_us [expr {[clock microseconds]-$tick}]
        vs::save $::vs::last_statistics $out/cache.tsv
    }
    close $metrics
    sb::require [expr {[lindex [exec sha256sum $checkpoint] 0] eq $sha_before}] "Input checkpoint changed"
    set f [open $out/COMPLETE.tcldict w]
    puts $f [dict merge $summary [dict create status PASS mode $mode input $checkpoint input_sha256 $sha_before version [version -short] cache_limit $::vs::property_limit checkpoint_written false placement_or_routing_run false]]
    close $f
    close_design
    exit 0
} message options]} {puts stderr [dict get $options -errorinfo];exit 1}
