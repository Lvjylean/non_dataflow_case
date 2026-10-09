# Focused read-only inventory mock; no Vivado process is used.
source [file join [file join [file dirname [info script]] code regional] core.tcl]
source [file join [file join [file dirname [info script]] code regional] regional.tcl]
source [file join [file join [file dirname [info script]] code regional] locality_inventory.tcl]
array set props {};set allcells {};set allnets {};set allports {};set loosepins {};array set netpins {};array set portnet {};array set sitecr {};array set crslr {};array set pinquery {}
proc cell {n ref loc {init {}} {async 0}} {
    global props allcells sitecr
    lappend allcells c:$n
    foreach {k v} [list NAME $n REF_NAME $ref LOC $loc INIT $init ASYNC_REG $async DONT_TOUCH 1] {set props(c:$n,$k) $v}
}
proc net {n type pins {fixed 0} {route {}}} {
    global allnets props netpins
    lappend allnets n:$n
    foreach {k v} [list NAME $n TYPE $type IS_ROUTE_FIXED $fixed FIXED_ROUTE $route] {set props(n:$n,$k) $v}
    set netpins(n:$n) {}
    foreach {p direction isclock} $pins {
        lappend netpins(n:$n) p:$p
        foreach {k v} [list NAME $p DIRECTION $direction IS_CLOCK $isclock] {set props(p:$p,$k) $v}
    }
}
proc port {name n {direction IN}} {global allports props portnet;lappend allports port:$name;set props(port:$name,NAME) $name;set props(port:$name,DIRECTION) $direction;set portnet(port:$name) n:$n}
proc get_property {p objs} {global props;set r {};foreach o $objs {if {![info exists props($o,$p)]} {error "Missing property $p on $o"};lappend r $props($o,$p)};if {[llength $objs]==1} {return [lindex $r 0]};return $r}
proc valuesarg {args option} {set i [lsearch -exact $args $option];if {$i<0} {return {}};return [lindex $args [expr {$i+1}]]}
proc get_cells {args} {global allcells;if {[lsearch -exact $args -hier]>=0} {return $allcells};set r {};foreach n [lindex $args end] {lappend r c:$n};return $r}
set props(c:protected,DONT_TOUCH) 1
proc get_nets {args} {
    global allnets portnet netpins props
    if {[lsearch -exact $args -hier]>=0} {return $allnets}
    if {[lsearch -exact $args -of_objects]>=0} {
        set out {};foreach o [valuesarg $args -of_objects] {
            if {[info exists portnet($o)]} {lappend out $portnet($o);continue}
            foreach n $allnets {if {[lsearch -exact $netpins($n) $o]>=0} {lappend out $n}}
        };return [lsort -unique $out]
    }
    set out {};foreach n [lindex $args end] {if {[string match n:* $n]} {lappend out $n} elseif {[info exists props(n:$n,NAME)]} {lappend out n:$n} else {error "Missing net $n"}}
    return $out
}
proc get_pins {args} {
    global allnets netpins props pinquery loosepins
    set out {};set flt [valuesarg $args -filter]
    if {[lsearch -exact $args -hier]>=0} {
        foreach n $allnets {foreach p $netpins($n) {if {$props($p,IS_CLOCK)} {lappend out $p}}};return [lsort -unique $out]
    }
    foreach n [valuesarg $args -of_objects] {
        if {[string match c:* $n]} {
            set cn [string range $n 2 end]
            foreach nn $allnets {foreach p $netpins($nn) {if {[file dirname $props($p,NAME)] eq $cn && $props($p,DIRECTION) eq "IN" && !$props($p,IS_CLOCK)} {lappend out $p}}}
            foreach p $loosepins {if {[file dirname $props($p,NAME)] eq $cn} {lappend out $p}}
            continue
        }
        if {![info exists pinquery($n)]} {set pinquery($n) 0};incr pinquery($n)
        foreach p $netpins($n) {if {$props($p,DIRECTION) eq "OUT" || !$props($p,IS_CLOCK)} {lappend out $p}}
    };return [lsort -unique $out]
}
proc get_ports {args} {global allports;return $allports}
proc get_slrs {args} {return {slr:SLR0 slr:SLR1}}
proc get_clock_regions {args} {global crslr;set r {};foreach cr [array names crslr] {if {$crslr($cr) eq [valuesarg $args -of_objects]} {lappend r $cr}};return $r}
proc get_sites {args} {global sitecr;set r {};foreach s [array names sitecr] {if {$sitecr($s) eq [valuesarg $args -of_objects]} {lappend r $s}};return $r}
foreach {slr cr site} {SLR0 X0Y0 SLICE_X0Y0 SLR1 X0Y4 SLICE_X0Y240} {
    set props(slr:$slr,NAME) $slr;set props(cr:$cr,NAME) $cr;set props(site:$site,NAME) $site
    set crslr(cr:$cr) slr:$slr;set sitecr(site:$site) cr:$cr
}
foreach {n ref loc init async} {
    src FDRE SLICE_X0Y240 1'b0 0
    root LUT1 SLICE_X0Y240 2'h2 0
    helper LUT1 SLICE_X0Y0 2'h2 0
    inv LUT1 SLICE_X0Y0 2'h1 0
    dst FDRE SLICE_X0Y0 1'b0 0
    async FDRE SLICE_X0Y0 1'b0 1
    fixed LUT2 SLICE_X0Y0 4'h8 0
    bound DSP48E2 SLICE_X0Y0 {} 0
    protected/lut LUT2 SLICE_X0Y0 4'h8 0
    mem URAM288 SLICE_X0Y0 {} 0
    cg BUFGCE SLICE_X0Y240 {} 0
    unknown LUT1 {} 2'h2 0
    portff FDRE SLICE_X0Y240 1'b0 0
    multi LUT2 SLICE_X0Y0 4'h8 0
} {cell $n $ref $loc $init $async}
net n_src SIGNAL {src/Q OUT 0 root/I0 IN 0 helper/I0 IN 0 bound/A[0] IN 0 protected/lut/I0 IN 0}
net n_root SIGNAL {root/O OUT 0 dst/D IN 0 inv/I0 IN 0}
net n_helper SIGNAL {helper/O OUT 0 mem/DIN_A[0] IN 0}
net n_fixed SIGNAL {fixed/O OUT 0 dst/CE IN 0} 0 {{node_a node_b}}
net n_const POWER {dst/R IN 0 src/CE IN 0}
net n_clock SIGNAL {cg/O OUT 0 src/C IN 1 dst/C IN 1}
net n_port SIGNAL {portff/D IN 0};port din n_port
net n_output SIGNAL {dst/Q OUT 0};port dout n_output OUT
net n_multi SIGNAL {multi/O OUT 0 fixed/I0 IN 0 inv/O OUT 0}
set loosepins {p:unknown/I0 p:mem/CAS_IN_ADDR_A[0]}
foreach p $loosepins {set props($p,NAME) [string range $p 2 end];set props($p,DIRECTION) IN;set props($p,IS_CLOCK) 0}
set out [file join /tmp locality_inventory_test_[pid]]
set result [locality_inventory::capture $out]
set f [open $out/cells.tsv];set data [read $f];close $f
set f [open $out/edges.tsv];set edges [read $f];close $f
proc check {ok why} {if {!$ok} {error $why}}
check [expr {[dict get $result status] eq "PASS"}] status
check [expr {[string first "root\tLUT1\tSLR1\t0\t4\t2'h2\t1\t" $data]>=0}] editable_identity
check [expr {[string first "src\tFDRE\tSLR1\t0\t4\t1'b0\t1\t" $data]>=0}] ff_init_and_protected_leaf_dont_touch_not_blocked
check [expr {[string first "src/Q\tbound/A\[0\]" $edges]>=0}] unsupported_sink_retained
check [expr {[string first "constant POWER\tsrc/CE" $edges]>=0}] constant_preserved
check [expr {[string first "src/C\n" $edges]<0}] clock_excluded
check [expr {[string first "barrier PORT:din\tportff/D" $edges]>=0}] input_port_barrier
check [expr {[string first "dst/Q\tbarrier PORT:dout" $edges]>=0}] output_port_barrier
check [expr {[string first "portff\tFDRE\tSLR1\t0\t4\t1'b0\t0\tport_boundary\n" $data]>=0}] input_port_is_not_ambiguous
foreach phrase {fixed_route protected_hierarchy asynchronous_register unknown_site_region ambiguous_driver_count unsupported_primitive} {check [expr {[string first $phrase $data]>=0}] $phrase}
foreach n [array names pinquery] {check [expr {$pinquery($n)==1}] "duplicate query:$n"}
check [expr {[dict get $result fixed_nets]==1}] fixed_property_without_flag
check [expr {[dict get $result disconnected_inputs]==2}] disconnected_input_count
check [expr {[string first "barrier UNCONNECTED:unknown/I0\tunknown/I0" $edges]>=0}] unconnected_comb_barrier
check [expr {[string first "mem\tURAM288\tSLR0\t0\t0\t\t1\t" $data]>=0}] ram_not_rejected_for_unused_cascade
# A new capture must invalidate every cached ancestor value.
set props(c:protected,DONT_TOUCH) 0
set result2 [locality_inventory::capture ${out}_second]
set f [open ${out}_second/cells.tsv];set data2 [read $f];close $f
check [expr {[string first "protected_hierarchy" $data2]<0}] capture_invalidates_protection
set f [open ${out}_second/runtime.tsv];set runtime [read $f];close $f
foreach phase {cells_and_protection protection_native_queries region_cache fixed_route_inventory canonical_clocks_ports routes_and_edges disconnected_inputs serialization} {
    check [expr {[string first $phase $runtime]>=0}] runtime_phase_$phase
}
file delete -force ${out}_second
puts "MOCK_PASS $result"
file delete -force $out
