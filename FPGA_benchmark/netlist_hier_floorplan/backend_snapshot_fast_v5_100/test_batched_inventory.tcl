# Complete graph equivalence including driver-side PARENT aliases and fallback.
set ::env(BL_INVENTORY_PROFILE) reference
source [file join [file dirname [info script]] test_locality_inventory.tcl]
unset ::env(BL_INVENTORY_PROFILE)
foreach n $allnets {set props($n,PARENT) $props($n,NAME)}
cell alias_dst FDRE SLICE_X0Y0 1'b0
net n_src_mid SIGNAL {}
net n_src_alias SIGNAL {alias_dst/D IN 0} 1
foreach n {n:n_src n:n_src_mid n:n_src_alias} {set props($n,PARENT) n_src_alias}
set props(n:n_src_mid,PARENT) n_src_alias
net n_clock_alias SIGNAL {alias_dst/C IN 1}
set props(n:n_clock_alias,PARENT) n_clock
array set top_by_parent {}
array set native_parent {};foreach n $allnets {set native_parent($n) $props($n,PARENT)}
foreach n $allnets {
    if {$n in {n:n_src_mid n:n_src_alias n:n_clock_alias}} {continue}
    set top_by_parent($props($n,PARENT)) $n
}
rename get_nets get_nets_original
set segment_queries 0;set net_name_resolutions 0
proc get_nets {args} {
    global allnets props native_parent top_by_parent segment_queries
    set top [expr {[lsearch -exact $args -top_net_of_hierarchical_group]>=0}]
    set seg [expr {[lsearch -exact $args -segments]>=0}]
    if {!$top && !$seg && [lsearch -exact $args -hier]<0 && [lsearch -exact $args -of_objects]<0} {incr ::net_name_resolutions}
    set result [get_nets_original {*}$args]
    if {$top} {
        set out {};foreach n $result {lappend out $top_by_parent($native_parent($n))}
        return [lsort -unique $out]
    }
    if {$seg} {
        incr segment_queries
        set groups {};foreach n $result {dict set groups $native_parent($n) 1}
        set out {};foreach n $allnets {if {[dict exists $groups $native_parent($n)]} {lappend out $n}}
        return $out
    }
    return $result
}
rename get_property get_property_original
set direction_queries 0
proc get_property {property objects} {
    if {$property eq "DIRECTION"} {incr ::direction_queries}
    return [get_property_original $property $objects]
}
proc contents {path {sorted 0}} {
    set f [open $path];set text [read $f];close $f
    if {$sorted} {return [lsort [split [string trimright $text \n] \n]]}
    return $text
}
set tmp /tmp/batched_inventory_[pid];file mkdir $tmp
set segment_queries 0;set direction_queries 0
set ref [locality_inventory::capture $tmp/reference reference]
set ref_segment_queries $segment_queries;set ref_direction_queries $direction_queries
set segment_queries 0;set direction_queries 0;set net_name_resolutions 0
set fast [locality_inventory::capture $tmp/batch batch]
check [expr {$net_name_resolutions == 0}] canonical_native_handles_never_resolved_by_name
check [expr {[dict get $fast acquisition_profile] eq "batch"}] batch_activated
foreach name {cells edges diagnostics} {
    check [expr {[contents $tmp/reference/$name.tsv 1] eq [contents $tmp/batch/$name.tsv 1]}] complete_${name}_equivalence
}
foreach field {cells editable_cells nets edges constant_edges clock_nets fixed_nets disconnected_inputs diagnostics semantics} {
    check [expr {[dict get $ref $field] eq [dict get $fast $field]}] metadata_$field
}
check [expr {$segment_queries==0 && $ref_segment_queries>0}] per_net_segments_eliminated
check [expr {$direction_queries<$ref_direction_queries}] pin_properties_batched
set batch_segment_queries $segment_queries;set batch_direction_queries $direction_queries
check [expr {[dict get $fast fixed_nets]==2}] fixed_alias_retained
check [expr {[string first "src/Q\talias_dst/D" [contents $tmp/batch/edges.tsv]]>=0}] alias_load_retained
check [expr {[catch {locality_inventory::activate}]}] no_metadata_reuse_outside_read_context
vs::with inventory_metadata_test {
    locality_inventory::activate
    check [expr {[locality_inventory::cell_metadata alias_dst] eq ""}] different_epoch_metadata_falls_back
    locality_inventory::capture $tmp/same_epoch batch
    locality_inventory::activate
    check [expr {[dict get [locality_inventory::cell_metadata alias_dst] slr] eq "SLR0"}] same_snapshot_cell_metadata
    check [expr {[locality_inventory::cell_metadata missing] eq ""}] missing_metadata_falls_back
}
check [expr {[catch {locality_inventory::cell_metadata alias_dst}]}] stale_metadata_rejected
locality_inventory::deactivate
check [expr {[locality_inventory::cell_metadata alias_dst] eq ""}] inactive_metadata_empty
set saved $props(n:n_src_mid,PARENT);set props(n:n_src_mid,PARENT) ""
set fallback [locality_inventory::capture $tmp/fallback batch]
set props(n:n_src_mid,PARENT) $saved
check [expr {[dict get $fallback acquisition_profile] eq "reference" && [dict get $fallback fallback_reason] ne ""}] invalid_parent_complete_fallback
foreach name {cells edges diagnostics} {
    check [expr {[contents $tmp/reference/$name.tsv 1] eq [contents $tmp/fallback/$name.tsv 1]}] fallback_${name}_equivalence
}
puts "BATCH_INVENTORY_PASS roots=[dict get $fast nets] segments_native=$ref_segment_queries->$batch_segment_queries direction_calls=$ref_direction_queries->$batch_direction_queries"
file delete -force $tmp
# Missing vectors and ambiguous canonical identities must fail closed.
set objects {n:n_src n:n_root}
set roots [locality_inventory::canonical_index $objects index]
check [expr {$roots eq {n_root n_src} && $index(n_src) eq "n:n_src"}] sorted_native_handle_index
unset index
set saved $props(n:n_root,NAME);set props(n:n_root,NAME) n_src
check [catch {locality_inventory::canonical_index $objects ambiguous}] ambiguous_handle_rejected
set props(n:n_root,NAME) $saved
set saved $props(n:n_root,NAME);set props(n:n_root,NAME) {}
check [catch {locality_inventory::canonical_index $objects missing}] missing_name_rejected
set props(n:n_root,NAME) $saved
