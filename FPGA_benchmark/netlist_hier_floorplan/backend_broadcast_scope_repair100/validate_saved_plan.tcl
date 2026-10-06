# Validate serialized plan commands without evaluating their contents.
set f [open [lindex $argv 0]]
set first [gets $f]
if {$first ne {set sb_plan {}}} {error "Unexpected plan initialization"}
set rows 0
while {[gets $f line]>=0} {
    if {[string trim $line] eq ""} {continue}
    if {[llength $line]!=5 || [lrange $line 0 2] ne {dict set sb_plan}} {error "Unsafe or unexpected serialized plan command"}
    # The producer serializes each command with Tcl list quoting. Exact list
    # roundtrip excludes substitutions or separators outside quoted arguments.
    if {[list {*}$line] ne $line} {error "Plan is not canonical Tcl list serialization"}
    incr rows
}
close $f
if {$rows<5} {error "Incomplete plan"}
puts "SAFE_SERIALIZED_PLAN rows=$rows"
