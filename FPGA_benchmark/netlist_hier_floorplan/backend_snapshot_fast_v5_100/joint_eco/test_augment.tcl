source [lindex $argv 0]
namespace eval sb {}
proc sb::require {ok why} {if {!$ok} {error $why}}
namespace eval rf {}
source [lindex $argv 1]
set config [dict create branch_limit 96]
set node [dict create name rfd_lut_1 loads {old/D}]
set root [dict create driver src/Q frontier {rfd_lut_1/I0} nodes [list $node] sinks {old/D}]
set region [dict create roots [list $root] config $config]
set cert [dict create expected [dict create rfd_lut_1/O {old/D new/I0}]]
set result [jc::augment_regional $region $cert]
sb::require [expr {[dict get [lindex [dict get $result roots] 0] sinks] eq {new/I0 old/D}}] "Lost endpoint coverage"
set cert [dict create expected [dict create rfd_lut_1/O {}]]
sb::require [catch {jc::augment_regional $region $cert}] "Empty distribution branch accepted"
puts {PASS regional exact-tree augmentation and empty-branch rejection}

set a [dict create ref LUT6 init 64'h1]
set b {"ref" "LUT6" "init" "64'h1"}
sb::require [jc::config_equal $a $b] "Quoted dictionary equivalence rejected"
dict set b init 64'h2
sb::require [expr {![jc::config_equal $a $b]}] "Changed INIT accepted"
puts {PASS configuration field equality and altered-truth-table rejection}
