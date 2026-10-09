# Exercise complete production verifiers against the same immutable native
# object model, with eager typed reads and native reference mode selected only
# through VS reuse. No Vivado process or production design is modified.
set here [file dirname [file normalize [info script]]]
source $here/test_verification_snapshot.tcl
source $here/code/regional/local_broadcast.tcl
rename lb::log lb::original_test_log
proc lb::log {message} {}
rename get_property original_model_property
rename get_cells original_model_cells
rename get_pins original_model_pins
rename get_nets original_model_nets
rename get_sites original_model_sites
rename get_slrs original_model_slrs
array set native_collections {}
array set pblock_members {}
proc native_collection {objects} {
    # Preserve significant representation as an opaque native collection stand-in.
    set result [join $objects {   }]
    set ::native_collections($result) 1
    return $result
}
proc get_property {property objects} {
    hit property_$property
    if {[llength $objects] > 1 && ![info exists ::native_collections($objects)]} {error "Native collection reconstructed: $property"}
    set values {}
    foreach object $objects {
        if {$property eq "CLASS"} {
            set classes {c cell p pin n net pb pblock site site slr slr port port}
            lappend values [dict get $classes [lindex [split $object :] 0]]
        } else {
            if {![info exists ::props($object,$property)]} {error "unknown_property:$property:$object"}
            lappend values $::props($object,$property)
        }
    }
    if {[llength $objects] == 1} {return [lindex $values 0]}
    if {[info exists ::batch_failure_property] && $property eq $::batch_failure_property} {return [lrange $values 0 end-1]}
    return $values
}
proc get_cells {args} {
    hit cells
    set i [lsearch -exact $args -of_objects]; set objects {}
    if {$i >= 0} {
        foreach pb [lindex $args [expr {$i+1}]] {lappend objects {*}$::pblock_members($pb)}
    } elseif {[lsearch -exact $args -hier] >= 0} {
        foreach key [array names ::props {c:*,NAME}] {lappend objects [string range $key 0 end-5]}
        set filter [lindex $args [expr {[lsearch -exact $args -filter]+1}]]; set accepted {}
        foreach object $objects {
            set ref $::props($object,REF_NAME)
            if {[string first {REF_NAME =~ FD*} $filter] >= 0 && ![string match FD* $ref]} {continue}
            if {[string first {REF_NAME =~ LUT*} $filter] >= 0 && ![string match LUT* $ref]} {continue}
            if {[string first {REF_NAME =~ MUXF*} $filter] >= 0 && ![string match MUXF* $ref]} {continue}
            lappend accepted $object
        }
        set objects $accepted
    } else {
        foreach name [lindex $args end] {
            if {[info exists ::props(c:$name,NAME)]} {lappend objects c:$name}
            if {[info exists ::ambiguous_cell] && $name eq $::ambiguous_cell} {lappend objects c:shadow}
        }
    }
    return [native_collection [lsort $objects]]
}
proc get_pins {args} {
    hit pins
    set objects {}; set i [lsearch -exact $args -of_objects]
    if {$i < 0} {
        foreach name [lindex $args end] {
            if {[info exists ::props(p:$name,NAME)]} {lappend objects p:$name}
            if {[info exists ::ambiguous_pin] && $name eq $::ambiguous_pin} {lappend objects p:shadow/D}
        }
    } else {
        foreach object [lindex $args [expr {$i+1}]] {
            foreach array_name {pins_by_cell pins_by_net} {
                if {[info exists ::${array_name}($object)]} {lappend objects {*}[set ::${array_name}($object)]}
            }
        }
    }
    set i [lsearch -exact $args -filter]
    if {$i >= 0} {
        set filter [lindex $args [expr {$i+1}]]; set accepted {}
        foreach object $objects {
            if {[string first {DIRECTION == IN} $filter] >= 0 && $::props($object,DIRECTION) ne "IN"} {continue}
            if {[string first {DIRECTION == OUT} $filter] >= 0 && $::props($object,DIRECTION) ne "OUT"} {continue}
            lappend accepted $object
        }
        set objects $accepted
    }
    return [native_collection [lsort -unique $objects]]
}
proc get_nets {args} {
    hit nets
    set i [lsearch -exact $args -of_objects];set objects {}
    if {$i >= 0} {
        foreach pin [lindex $args [expr {$i+1}]] {lappend objects {*}$::connected($pin)}
    } else {
        foreach name [lindex $args end] {
            if {[info exists ::segments($name)]} {lappend objects $name} elseif {[info exists ::segments(n:$name)]} {lappend objects n:$name}
        }
    }
    if {[lsearch -exact $args -segments] >= 0} {
        set all {};foreach net $objects {lappend all {*}$::segments($net)};set objects $all
    }
    if {[lsearch -exact $args -top_net_of_hierarchical_group] >= 0} {
        set all {};foreach net $objects {lappend all $::props($net,ROOT)};set objects $all
    }
    return [native_collection [lsort -unique $objects]]
}
proc get_pblocks {args} {
    set objects {};foreach name [lindex $args end] {
        if {$name eq "*"} {lappend objects {*}[array names ::pblock_members]} elseif {[info exists ::pblock_members(pb:$name)]} {lappend objects pb:$name}
    }
    return [native_collection [lsort -unique $objects]]
}
proc get_sites {args} {hit sites;return [native_collection site:zero]}
proc get_slrs {args} {hit slrs;return [native_collection slr:zero]}
proc model_cell {name ref {init 1'b0}} {
    foreach {property value} [list NAME $name REF_NAME $ref INIT $init LOC SLICE_X0Y0 BEL AFF PBLOCK localrep_SLR0 \
            DONT_TOUCH true IS_LOC_FIXED 0 IS_BEL_FIXED 0 IS_C_INVERTED {} IS_D_INVERTED false IS_R_INVERTED 0 IS_S_INVERTED 0] {
        set ::props(c:$name,$property) $value
    }
}
proc model_net {name {type SIGNAL}} {
    set object n:$name
    set ::props($object,NAME) $name;set ::props($object,TYPE) $type;set ::props($object,ROOT) $object
    set ::segments($object) [list $object];set ::pins_by_net($object) {}
}
proc model_pin {name direction net} {
    set object p:$name
    set ::props($object,NAME) $name;set ::props($object,DIRECTION) $direction
    set ::connected($object) [list n:$net]
    lappend ::pins_by_net(n:$net) $object
    lappend ::pins_by_cell(c:[file dirname $name]) $object
}
proc typed_fixture {} {
    foreach a {props connected segments pins_by_cell pins_by_net native_calls native_collections pblock_members} {array unset ::$a *}
    foreach v {ambiguous_cell ambiguous_pin batch_failure_property} {unset -nocomplain ::$v}
    vs::clear_legacy
    set ::props(site:zero,NAME) SLICE_X0Y0;set ::props(slr:zero,NAME) SLR0
    set ::props(port:din,NAME) din
    foreach name {clock data set_data port ground power buffer_out mux_out} {model_net $name}
    set ::props(n:power,TYPE) POWER;set ::props(n:ground,TYPE) GROUND
    set roots {};set graph [dict create replicas {} moves {} new_inputs {} expected {}]
    foreach {name ref init input_spec output net} {
        source FDRE {} {D port C clock CE power R ground} Q data
        set_source FDSE {} {D port C clock CE power S ground} Q set_data
        buffer LUT1 2'H2 {I0 data} O buffer_out
        mux MUXF7 {} {I0 data I1 set_data S ground} O mux_out
    } {
        model_cell $name $ref $init
        foreach {pin connection} $input_spec {model_pin $name/$pin IN $connection}
        model_pin $name/$output OUT $net
        set inputs {}
        foreach {pin connection} $input_spec {
            set signal [sb::signal $name/$pin]
            set key [expr {$connection eq "data" ? "source/Q" : $connection eq "set_data" ? "set_source/Q" : $signal}]
            dict set inputs $pin [dict create key $key]
            dict set snapshot_nets $key [dict create signal $signal kind ordinary anchor $name/$pin]
        }
        dict set roots $name/$output [dict create cell $name ref $ref pin $output config [sb::config $name] inputs $inputs]
        for {set i 0} {$i < 16} {incr i} {
            set copy [format {%s_copy[%d]} $name $i];set sink [format {%s_sink[%d]} $name $i]
            model_cell $copy $ref $init;model_cell $sink FDRE
            model_net ${copy}_output
            model_pin $copy/$output OUT ${copy}_output;model_pin $sink/D IN ${copy}_output
            foreach {pin connection} $input_spec {
                model_pin $copy/$pin IN $connection
                dict set graph new_inputs $copy/$pin [dict get $inputs $pin key]
            }
            dict set graph replicas $copy [dict create key $name/$output slr SLR0]
            dict set graph expected $copy/$output [list $sink/D]
            lappend ::pblock_members(pb:localrep_SLR0) c:$copy
        }
    }
    # Original cell and Pblock share their displayed NAME; complete membership
    # still includes every hierarchy/member and is compared byte-for-byte.
    set ::pblock_members(pb:source) {c:source c:buffer}
    foreach name {source localrep_SLR0} {
        foreach {property value} [list NAME $name GRID_RANGES {SLICE_X0Y0:SLICE_X1Y1} IS_SOFT [expr {$name eq "source"}] PARENT {}] {set ::props(pb:$name,$property) $value}
    }
    set original [lb::pblock_snapshot]
    set local [dict create snapshot [dict create roots $roots nets $snapshot_nets] graph $graph original_pblocks [dict create source [dict get $original source]] reused_positions {buffer SLR0}]
    set counts [sb::counts]
    set ::plan [dict create counts_before [dict replace $counts ff [expr {[dict get $counts ff]-32}] lut [expr {[dict get $counts lut]-16}]] ff_added 32 lut_added 16 \
        ce {} data {} fixed {} ce_bound {} ce_endpoints {} tracked {} local_broadcast $local]
    array unset ::native_calls *;vs::clear_legacy
}
proc verification_run {out placed reuse} {
    global plan
    set ::vs::reuse $reuse
    set old_channels [file channels]
    set code [catch {vs::with full_verification {
        sb::verify $plan $out $placed
        lb::verify $plan $out $placed
    }} result]
    foreach ch [file channels] {if {$ch ni $old_channels} {close $ch}}
    set files {}
    foreach path [lsort [glob -nocomplain $out/*]] {
        set f [open $path];dict set files [file tail $path] [read $f];close $f
    }
    return [dict create code $code result $result files $files stats $::vs::last_statistics calls [array get ::native_calls]]
}
set out [file join /tmp typed_verification_[pid]]
set cases 0
proc compare_typed {label mutation {placed 1} {failure {}}} {
    global out cases
    typed_fixture;uplevel #0 $mutation
    set reference [verification_run $out/$label/native $placed 0]
    vs::clear_legacy;array unset ::native_calls *
    set cached [verification_run $out/$label/cached $placed 1]
    foreach key {code result files} {check [expr {[dict get $reference $key] eq [dict get $cached $key]}] "Full verification changed: $label/$key"}
    if {$failure eq {}} {check [expr {[dict get $cached code] == 0}] "Unexpected failure: $label/[dict get $cached result]"} else {
        check [expr {[dict get $cached code] == 1 && [string first $failure [dict get $cached result]] >= 0}] "Lost native failure: $label/[dict get $cached result]"
    }
    check [expr {!$::vs::active && ![array size ::sb::cell_objects] && ![array size ::sb::pin_objects]}] "Object lifetime escaped: $label"
    incr cases
    return [list $reference $cached]
}
lassign [compare_typed placed {}] reference cached
check [expr {[dict size [dict get $cached files]] == 7}] all_reports_compared
check [expr {[dict get $cached stats native_class_calls] == 0}] typed_paths_avoid_class
check [expr {[dict get $cached calls property_INIT] < [dict get $reference calls property_INIT]/8}] primitive_properties_batched
check [expr {[dict get $cached calls cells] < [dict get $reference calls cells]/8}] lazy_cells_feed_batch
puts "TYPED_COUNTERS reference_INIT=[dict get $reference calls property_INIT] cached_INIT=[dict get $cached calls property_INIT] reference_cells=[dict get $reference calls cells] cached_cells=[dict get $cached calls cells] class=[dict get $cached stats native_class_calls] prefetch_batches=[dict get $cached stats prefetch_batches]"
# Populate the original verifier's data, CE, endpoint, fixed-cell and tracked
# net rules as well; both procedures still emit the same seven full reports.
proc include_legacy_rules {} {
    set inputs [sb::inputs source]
    set helper [dict create config [sb::config buffer] leaves [sb::loads buffer/O] position [sb::position buffer]]
    dict set ::plan data source [dict create config [sb::config source] inputs $inputs source_slr SLR0 replicas {} \
        groups [dict create SLR0 [sb::loads source/Q]] helpers [dict create buffer $helper]]
    dict set ::plan ce buffer [dict create config [sb::config buffer] inputs [sb::inputs buffer] loads [sb::loads buffer/O] target_slr SLR0]
    dict set ::plan ce_bound set_source SLR0
    dict set ::plan ce_endpoints set_source [dict create config [sb::config set_source] inputs [sb::inputs set_source] qloads [sb::loads set_source/Q]]
    dict set ::plan fixed {source_sink[0]} [sb::position {source_sink[0]}]
    dict set ::plan tracked data [dict create before [sb::loads source/Q] added {} removed {}]
    vs::clear_legacy;array unset ::native_calls *
}
compare_typed legacy_and_local {include_legacy_rules}
compare_typed legacy_changed_d {include_legacy_rules;set ::connected(p:source/D) n:ground} 1 {FF input changed}
compare_typed legacy_changed_helper {include_legacy_rules;set ::props(c:buffer,INIT) 2'h1} 1 {CE truth table changed}
compare_typed unplaced {} 0
lassign [compare_typed incomplete_native_vector {set ::batch_failure_property INIT}] vector_reference vector_cached
check [expr {[dict get $vector_cached stats prefetch_fallbacks] > 0}] incomplete_vector_falls_back
compare_typed missing_config {unset {::props(c:source_copy[15],IS_R_INVERTED)}} 1 {unknown_property:IS_R_INVERTED}
compare_typed config {set {::props(c:source_copy[15],INIT)} 1'b1} 1 {Replica function mismatch}
compare_typed missing_cell {unset {::props(c:source_copy[15],NAME)}} 1 {Unexpected ff count change}
compare_typed ambiguous_cell {set ::ambiguous_cell {source_copy[15]};model_cell shadow BUF} 1 {Missing/ambiguous cell}
compare_typed missing_pin {unset {::props(p:source_copy[15]/D,NAME)}} 1 {Missing/ambiguous pin}
compare_typed ambiguous_pin {set ::ambiguous_pin {source_copy[15]/D};model_pin shadow/D IN port} 1 {Missing/ambiguous pin}
compare_typed unknown_protection {unset {::props(c:source_copy[15],DONT_TOUCH)}} 1 {unknown_property:DONT_TOUCH}
compare_typed unprotected {set {::props(c:source_copy[15],DONT_TOUCH)} false} 1 {Replica unprotected}
compare_typed locked {set {::props(c:source_copy[15],IS_LOC_FIXED)} true} 1 {Replica acquired exact location lock}
compare_typed input {set {::connected(p:source_copy[15]/D)} n:ground} 1 {Local input mismatch}
compare_typed sink {set {::pins_by_net(n:source_copy[15]_output)} {p:source_copy[15]/Q}} 1 {Local output sink mismatch}
compare_typed membership {set ::pblock_members(pb:localrep_SLR0) [lrange $::pblock_members(pb:localrep_SLR0) 0 end-1]} 1 {Replica missing from SLR Pblock}
compare_typed floorplan {lappend ::pblock_members(pb:source) c:mux} 1 {Original floorplan changed}
compare_typed reused_identity {set ::props(c:buffer,INIT) 2'h1} 1 {Original local function changed}
set limits [list $::vs::query_limit $::vs::query_object_limit $::vs::property_limit]
set ::vs::query_limit 0;set ::vs::query_object_limit 0;set ::vs::property_limit 0
compare_typed budget {} 1
lassign $limits ::vs::query_limit ::vs::query_object_limit ::vs::property_limit
# Repeat every rule within one immutable stage. Reports are regenerated and no
# primitive/native membership read is needed on the second completed checker.
typed_fixture
set ::vs::reuse 1
vs::begin repeated_full_verification
foreach pass {first second} {
    set directory $out/repeated/$pass
    sb::verify $::plan $directory 1;lb::verify $::plan $directory 1
    set reports {}
    foreach path [lsort [glob $directory/*]] {
        set f [open $path];dict set reports [file tail $path] [read $f];close $f
    }
    if {$pass eq "first"} {set first_reports $reports;set first_init $::native_calls(property_INIT)} else {
        check [expr {$first_reports eq $reports && $first_init == $::native_calls(property_INIT)}] repeated_full_evidence
    }
}
vs::end
# All objects come from native queries, including identical displayed names.
typed_fixture
vs::begin same_name_typed
set cell [vs::query get_cells -quiet source];set pb [vs::query get_pblocks -quiet source]
check [expr {[vs::property NAME $cell cell] eq [vs::property NAME $pb pblock]}] same_name_fixture
check [expr {[vs::property INIT $cell cell] eq {}}] same_name_cell_config
check [expr {[vs::property IS_SOFT $pb pblock] == 1}] same_name_pblock_config
check [expr {[llength [vs::query_from cell get_pins -of_objects $cell]] == 5}] same_name_cell_pins
check [expr {[llength [vs::query_from pblock get_cells -quiet -of_objects $pb]] == 2}] same_name_pblock_members
set stats [vs::end];check [expr {[dict get $stats native_class_calls] == 0}] same_name_no_class
# Force equal string representations, as actual Vivado native objects can have,
# while native query provenance supplies each class. No name-to-type registry is
# used: explicit class keys isolate both properties and -of_objects queries.
rename get_cells typed_model_cells
rename get_nets typed_model_nets
rename get_pins typed_model_pins
rename get_pblocks typed_model_pblocks
rename get_property typed_model_property
proc get_cells {args} {if {$args eq {-quiet collision}} {set ::collision_type cell;return collision};return [typed_model_cells {*}$args]}
proc get_nets {args} {if {$args eq {-quiet collision}} {set ::collision_type net;return collision};return [typed_model_nets {*}$args]}
proc get_pblocks {args} {if {$args eq {-quiet collision}} {set ::collision_type pblock;return collision};return [typed_model_pblocks {*}$args]}
proc get_pins {args} {
    if {$args eq {-of_objects collision}} {return [list $::collision_type/pin]}
    return [typed_model_pins {*}$args]
}
proc get_property {property objects} {
    if {$objects eq "collision"} {
        if {$property eq "CLASS"} {error "Unexpected CLASS for typed native collection"}
        if {$property eq "LABEL"} {return $::collision_type}
    }
    return [typed_model_property $property $objects]
}
vs::begin equal_native_strings
foreach class {cell net pblock} command {get_cells get_nets get_pblocks} {
    set object [vs::query $command -quiet collision]
    check [expr {[vs::property LABEL $object $class] eq $class}] "Equal native string property collision: $class"
    check [expr {[vs::query_from $class get_pins -of_objects $object] eq [list $class/pin]}] "Equal native string query collision: $class"
}
foreach class {cell net pblock} command {get_cells get_nets get_pblocks} {
    set ::collision_type wrong_type
    set object [vs::query $command -quiet collision]
    check [expr {[vs::property LABEL $object $class] eq $class}] "Equal native string cached property collision: $class"
    check [expr {[vs::query_from $class get_pins -of_objects $object] eq [list $class/pin]}] "Equal native string cached query collision: $class"
}
vs::end
foreach command {get_cells get_nets get_pins get_pblocks get_property} helper {cells nets pins pblocks property} {rename $command {};rename typed_model_$helper $command}
# Mutation traces remain active in native reference and typed-prefetch modes.
foreach reuse {0 1} {
    set ::vs::reuse $reuse
    set before $::props(c:source,INIT)
    set code [catch {vs::with mutation {
        sb::verification_prefetch source source source/D
        catch {set_property INIT 1'b1 [sb::cell source]}
        catch {sb::config source}
    }} why]
    check [expr {$code && [string first {Mutation is forbidden} $why] >= 0 && $::props(c:source,INIT) eq $before}] typed_mutation_guard
}
set ::vs::reuse 1
vs::begin stale_context
sb::verification_prefetch source source source/D
vs::invalidate physical_boundary
check [expr {[catch {sb::config source} why] && [string first invalidated $why] >= 0}] invalidated_cached_object
check [expr {[catch {sb::pin source/D} why] && [string first invalidated $why] >= 0}] invalidated_cached_pin
vs::end
set ::props(c:source,INIT) 1'b1
check [expr {[dict get [vs::with reopened {sb::config source}] INIT] eq "1'b1"}] independent_configuration_fresh
set ::connected(p:source/D) n:ground
check [expr {[vs::with placed_stage {sb::signal source/D}] eq {constant GROUND}}] independent_connectivity_fresh
file delete -force $out
puts "PASS: $cases complete report/error comparisons, FDRE/FDSE default and LUT/MUX semantics, typed batches, same-name classes, original native collections, capacity fallback, mutation and independent-stage freshness"
