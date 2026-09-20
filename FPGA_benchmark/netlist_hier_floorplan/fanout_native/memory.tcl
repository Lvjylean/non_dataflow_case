# Pre-placement identity trees for memory and unsupported buffer/port drivers.
# No LOC query, CR-specific helper placement, or additional register is needed.
proc hf2::owner {pin} {
    set name [string range $pin 0 [expr {[string last / $pin]-1}]]
    while {$name ne ""} {
        if {[info exists ::cf_owner($name)]} {return $::cf_owner($name)}
        set slash [string last / $name]
        if {$slash < 0} {break}
        set name [string range $name 0 [expr {$slash-1}]]
    }
    return UNASSIGNED
}

proc hf2::tree_plan {pins retained placed} {
    variable cfg
    set target [dict get $cfg memory_target]
    set root_limit [expr {$target-$retained}]
    if {$root_limit < 1} {error RETAINED_ROOT_LOADS_EXHAUST_TARGET}
    set buckets [dict create]
    foreach pin $pins {
        set key [expr {$placed ? [site_key $pin] : [owner $pin]}]
        dict lappend buckets $key $pin
    }
    set units {}
    # Keep the exact dictionary ordering without per-key lookups in a large map.
    set ordered {}
    dict for {key group} $buckets {lappend ordered [list $key $group]}
    foreach entry [lsort -dictionary -index 0 $ordered] {
        set group [lsort -dictionary [lindex $entry 1]]
        if {$placed} {
            if {[llength $group] > $target} {error SHARED_SITE_GROUP_EXCEEDS_TARGET}
            lappend units $group
        } else {
            for {set i 0} {$i < [llength $group]} {incr i $target} {lappend units [lrange $group $i [expr {$i+$target-1}]]}
        }
    }
    set plan {}; set frontier $pins; set level 0
    while {[llength $frontier] > $root_limit} {
        set groups {}; set group {}
        foreach unit $units {
            if {[llength $group]+[llength $unit] > $target} {lappend groups $group; set group {}}
            lappend group {*}$unit
        }
        if {[llength $group]} {lappend groups $group}
        if {[llength $groups] >= [llength $frontier]} {error TREE_PLAN_DID_NOT_PROGRESS}
        set frontier {}; set units {}
        foreach group $groups {
            set name f96_identity_[incr ::f96::serial]
            incr ::f96::created
            lappend plan [list $name $level BOUNDED_IDENTITY $group]
            lappend frontier $name/I0; lappend units [list $name/I0]
        }
        incr level
    }
    return [list $plan $frontier $level]
}
