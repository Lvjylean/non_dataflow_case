source [file join [file dirname [info script]] physical_eco.tcl]
proc check {value msg} {if {!$value} {error $msg}}
set normal {# of unplaced cells................ : 0 :
# of sites with errors............. : 0 :}
check [expr {[dict get [plg::parse_place $normal] site_errors] == 0}] "Valid report rejected"
set broken {# of unplaced cells................ : 0 :
# of sites with errors............. : 2 :
# of sites with placement errors... : 1 :
# of sites with invalid routed sites.. : 1 :
Invalid Routed Sites
SLICE_X2Y3
Error(s)
Invalid site found
Illegal Placement Sites
SLICE_X4Y5
Error(s)
LUT6 conflict}
set parsed [plg::parse_place $broken]
check [expr {[dict get $parsed illegal_sites] eq "SLICE_X4Y5"}] "Illegal site parser"
check [expr {[dict get $parsed routed_sites] eq "SLICE_X2Y3"}] "Stale route parser"
check [catch {plg::parse_place "truncated report"}] "Missing fields accepted"
check [catch {plg::parse_place [string map {{errors............. : 2} {errors............. : 3}} $broken]}] "Unknown error category accepted"
set routed_report {# of routable nets..................... : 2 :
# of fully routed nets................. : 2 :
# of nets with routing errors........... : 0 :}
plg::check_route_report $routed_report
check [catch {plg::check_route_report [string map {{nets................. : 2} {nets................. : 1}} $routed_report]}] "Partial routing accepted"
check [catch {plg::check_route_report "$routed_report\n# of unrouted nets : 1 :"}] "Explicit unrouted nets accepted"
check [catch {plg::check_route_report "truncated report"}] "Missing routing evidence accepted"
# A failed physical gate must never reach the caller's route command.
rename plg::status plg::native_status
proc plg::status {out} {return $::status}
set status [dict create unplaced 0 placement_errors 1 invalid_routed_sites 0 site_errors 1]
set routed 0
check [catch {plg::before_route /unused; set routed 1}] "Illegal packing accepted"
check [expr {!$routed}] "Route proceeded after invalid packing"
dict set status placement_errors 0; dict set status unplaced 1
check [catch {plg::before_route /unused; set routed 1}] "Unplaced cell accepted"
# One bounded escalation, then fail; do not loop or run the router.
proc place_design {args} {incr ::places}
rename plg::repair_sites plg::native_repair_sites
proc plg::repair_sites {state out} {incr ::repairs}
set status [dict create unplaced 0 placement_errors 1 invalid_routed_sites 0 site_errors 1]
set places 0;set repairs 0
check [catch {plg::place /unused -no_psip}] "Persistent illegal packing accepted"
check [expr {$places == 2 && $repairs == 1}] "Unbounded repair or wrong number of placements"
puts "PASS: report parsing, fail-closed pre-route gate, unplaced rejection, bounded repair"
