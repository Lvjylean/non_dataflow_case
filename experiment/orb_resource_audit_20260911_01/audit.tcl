set_param general.maxThreads 2
open_checkpoint /Projects/jinyang/workspace/non_dataflow_crossSLR/case/experiment/orb_pu256_bramfix_20260911_03/pu256/routed.dcp
set f [open resource_identity.txt w]
puts $f "part=[get_property PART [current_design]]"
puts $f "top=[get_property NAME [current_design]]"
puts $f "hamming_instances=[llength [get_cells -hier -filter {REF_NAME =~ *computeHamming*}]]"
set cells [get_cells -hier -filter {IS_PRIMITIVE == 1}]
set sites [get_sites -quiet -of_objects $cells]
set regions [lsort -unique [get_clock_regions -quiet -of_objects $sites]]
puts $f "occupied_clock_regions=$regions"
puts $f "occupied_clock_region_count=[llength $regions]"
close $f
report_utilization -file utilization.rpt
report_utilization -hierarchical -file hierarchy.rpt
set f [open verified.txt w]; puts $f [clock format [clock seconds]]; close $f
