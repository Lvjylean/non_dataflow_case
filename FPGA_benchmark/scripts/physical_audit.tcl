# Read-only inventory of primitive placement by clock region.
set_param general.maxThreads 4
open_checkpoint $::env(AUDIT_DCP)
set f [open clock_route_status.txt w]
foreach net [get_nets -of_objects [get_ports -filter {NAME == aclk}]] {
 puts $f "$net: [get_property ROUTE_STATUS $net]"
 report_property -all $net -file clock_net_properties.txt
}
puts $f "Partial nets: [get_nets -quiet -hier -filter {ROUTE_STATUS == PARTIAL}]"
close $f
set site_region [dict create]
foreach cr [get_clock_regions] {
 foreach site [get_sites -of_objects $cr] {dict set site_region $site $cr}
}
set cells [get_cells -hier -filter {IS_PRIMITIVE == 1}]
set refs [get_property REF_NAME $cells]
set locs [get_property LOC $cells]
set counts [dict create]
set unknown 0
foreach cell $cells ref $refs loc $locs {
 if {$ref eq "GND" || $ref eq "VCC"} {continue}
 if {$loc eq "" || ![dict exists $site_region $loc]} {
  incr unknown
  continue
 }
 set cr [dict get $site_region $loc]
 dict incr counts [list $cr $ref]
}
set f [open clock_region_primitives.tsv w]
puts $f "clock_region\tprimitive_type\tcount"
foreach key [lsort [dict keys $counts]] {
 lassign $key cr ref
 puts $f "$cr\t$ref\t[dict get $counts $key]"
}
close $f
set f [open audit_summary.txt w]
puts $f "Nonconstant primitive locations without a clock-region mapping: $unknown"
puts $f "Counts are primitive instances, not occupied CLB sites or LUT resource equivalents."
close $f
set f [open report_utilization_help.txt w]
puts $f [report_utilization -help]
close $f
exit
