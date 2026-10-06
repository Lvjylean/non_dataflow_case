# Run in the Vivado GUI: source this script after opening the ECO result DCP.
# Cyan: new same-stage FFs; magenta: parallel local CE LUT copies.
set copies [get_cells -quiet sbeco_ff_*]
set enables [get_cells -quiet sbeco_ce_*]
if {![llength $copies] && ![llength $enables]} {error "No sbeco instances in the open design"}
if {[llength $copies]} {highlight_objects -color cyan $copies}
if {[llength $enables]} {highlight_objects -color magenta $enables}
select_objects [concat $copies $enables]
