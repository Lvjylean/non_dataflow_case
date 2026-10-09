# Only controller-authorized, source-bound timing-retry inventory reuse.
namespace eval bl_static_cache {variable module_dir [file dirname [info script]]}
proc bl_static_cache::prepare {folder} {
    variable module_dir
    if {![info exists ::env(BL_STATIC_CACHE_ENABLED)] || $::env(BL_STATIC_CACHE_ENABLED) ne "1"} {return 0}
    set clocks {}
    foreach name [lsort [sb::names [get_clocks -quiet *]]] {
        set obj [get_clocks -quiet [list $name]]
        lappend clocks [list $name [get_property PERIOD $obj] [get_property WAVEFORM $obj]]
    }
    set source_root [file normalize [file join $module_dir ../..]]
    set root $::env(COMPILEFAST_RUN_ROOT)
    set producer reopened_base
    if {[info exists ::compilefast::active] && $::compilefast::active} {set producer live_base}
    set args [list python3 $module_dir/static_discovery_cache.py begin $folder \
        --checkpoint $::input --source-root $source_root --source-manifest $root/source_manifest.json \
        --vivado-version [version -short] --part [get_property PART [current_design]] \
        --clocks $clocks --producer $producer]
    if {[catch {exec {*}$args} reason]} {
        lb::log "static_cache_context_unavailable $reason"
        return 0
    }
    if {[info exists ::env(BL_STATIC_CACHE_SOURCE)] && $::env(BL_STATIC_CACHE_SOURCE) ne ""} {
        if {[catch {exec python3 $module_dir/static_discovery_cache.py restore $folder --source $::env(BL_STATIC_CACHE_SOURCE)} result]} {
            lb::log "static_cache_restore_unavailable $result"
            return 0
        }
        lb::log "static_cache_restore=$result"
        return [expr {$result eq "HIT"}]
    }
    return 0
}
proc bl_static_cache::publish {folder} {
    variable module_dir
    if {![file exists $folder/static_context.json]} {return}
    if {[catch {exec python3 $module_dir/static_discovery_cache.py publish $folder} result]} {
        lb::log "static_cache_publish_unavailable $result"
    } else {lb::log "static_cache_publish=$result"}
}
