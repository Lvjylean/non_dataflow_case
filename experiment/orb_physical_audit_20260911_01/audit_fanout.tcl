# Discover physical nets once per hierarchical group; measure primitive sink pins.
proc fanout_scan {stage placed apply_constraints} {
    set f [open ${stage}_fanout.tsv w]
    puts $f "net\tdriver_pin\tdriver_ref\tlogical_loads\tphysical_site_pins\tclassification\tmax_fanout\tforce_max_fanout"
    set candidates [get_nets -hierarchical -segments -top_net_of_hierarchical_group -filter {FLAT_PIN_COUNT > 256}]
    set seen [dict create]
    set remaining {}; set eligible 0; set unsupported 0; set maxlogical 0; set maxphysical 0; set violations 0; set unknown 0
    if {$apply_constraints} {set xf [open ${stage}_maxfanout256.xdc w]}
    foreach net $candidates {
        set drivers [get_pins -quiet -leaf -of_objects $net -filter {DIRECTION == OUT}]
        set ports [get_ports -quiet -of_objects $net -filter {DIRECTION == IN}]
        set key [join [concat $drivers $ports] ,]
        if {$key eq ""} {set key $net}
        if {[dict exists $seen $key]} {continue}
        dict set seen $key 1
        set loads [get_pins -quiet -leaf -of_objects $net -filter {DIRECTION == IN}]
        set logical [llength $loads]
        if {$logical <= 256} {continue}
        set ref NONE; set class UNSUPPORTED; set physical NA; set dn $net
        if {[llength $ports]} {
            set class INPUT_PORT
            if {[llength [get_clocks -quiet -of_objects $ports]]} {set class CLOCK}
        } elseif {[llength $drivers] == 1} {
            set cell [get_cells -of_objects $drivers]
            set ref [get_property REF_NAME $cell]
            set dn [get_nets -of_objects $drivers]
            if {$ref in {GND VCC}} {
                set class CONSTANT
            } elseif {[llength [get_clocks -quiet -of_objects $drivers]]} {
                set class CLOCK
            } elseif {[string match BUFG* $ref]} {
                set class GLOBAL_CONTROL_BUFFER
            } elseif {[get_property DONT_TOUCH $cell] in {1 true TRUE} || [get_property DONT_TOUCH $dn] in {1 true TRUE}} {
                set class PROTECTED
            } elseif {[regexp {^(FD(RE|SE|CE|PE)?|LUT[1-6](_2)?)$} $ref]} {
                set class FD_LUT
            } elseif {[string match RAMB* $ref]} {
                set class BRAM_OUTPUT
            }
        }
        if {$class ni {CLOCK CONSTANT}} {
            set maxlogical [expr {max($maxlogical,$logical)}]
            if {$placed} {
                set sitepins [get_site_pins -quiet -of_objects $loads]
                set physical [llength [lsort -unique $sitepins]]
                if {$physical == 0} {set physical UNKNOWN; incr unknown} else {set maxphysical [expr {max($maxphysical,$physical)}]}
            }
            if {$apply_constraints && $class in {FD_LUT BRAM_OUTPUT}} {
                set_property MAX_FANOUT 256 $dn
                puts $xf [format {set_property MAX_FANOUT 256 [get_nets -of_objects [get_pins {%s}]]} $drivers]
                if {$class eq "FD_LUT"} {
                    set_property FORCE_MAX_FANOUT 256 $dn
                    puts $xf [format {set_property FORCE_MAX_FANOUT 256 [get_nets -of_objects [get_pins {%s}]]} $drivers]
                }
            }
            if {$placed && $physical ne "UNKNOWN" && $physical > 256} {incr violations}
            if {$class eq "FD_LUT"} {
                incr eligible
                lappend remaining $dn
            } else {incr unsupported}
        }
        puts $f "$net\t$key\t$ref\t$logical\t$physical\t$class\t[get_property MAX_FANOUT $dn]\t[get_property FORCE_MAX_FANOUT $dn]"
        flush $f
    }
    close $f
    if {$apply_constraints} {close $xf}
    set mf [open ${stage}_fanout_metrics.tsv w]
    puts $mf "metric\tvalue"
    puts $mf "physical_signal_violations\t$violations"
    puts $mf "unknown_physical_counts\t$unknown"
    puts $mf "fd_lut_above256_logical\t$eligible"
    puts $mf "other_signal_above256_logical\t$unsupported"
    puts $mf "max_signal_logical_loads_among_high_logical\t$maxlogical"
    puts $mf "max_signal_physical_site_pins_among_high_logical\t$maxphysical"
    close $mf
    puts "FANOUT_STAGE=$stage ELIGIBLE_ABOVE256=$eligible OTHER_ABOVE256=$unsupported MAX_LOGICAL=$maxlogical"
    return $remaining
}
