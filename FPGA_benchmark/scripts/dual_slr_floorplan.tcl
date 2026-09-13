# Count accelerator resources separately from shell resources.
set accel [get_cells -hier -filter {NAME =~ *vta64_kernel_1 && IS_PRIMITIVE == 0}]
if {[llength $accel] != 1} {error "Expected one VTA kernel, found $accel"}
create_pblock accelerator_two_slr
set regions [get_clock_regions -of_objects [get_slrs {SLR2 SLR3}]]
if {[llength $regions] == 0} {error "No clock regions for the selected SLR pair"}
foreach region $regions {resize_pblock [get_pblocks accelerator_two_slr] -add "CLOCKREGION_$region"}
add_cells_to_pblock [get_pblocks accelerator_two_slr] $accel
set_property IS_SOFT false [get_pblocks accelerator_two_slr]
