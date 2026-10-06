source [file join [file dirname [info script]] policy.tcl]
foreach {ref pin kind} {
    FDRE Q ff FDSE Q ff
    RAMB36E2 {DOUTADOUT[25]} bram_data RAMB18E2 {DOUTBDOUT[3]} bram_data
    RAMB36E1 {DOADO[0]} bram_data URAM288 {DOUT_A[6]} uram_data
    URAM288_BASE {DOUT_B[3]} uram_data
    RAMB36E2 SBITERR unsupported RAMB36E2 CASDOUTA unsupported
    URAM288 SBITERR_A unsupported LUT1 O unsupported BUFG O unsupported
    FDRE C unsupported RAMB36E2 {ADDRARDADDR[0]} unsupported
} {
    sb::require [expr {[sb::data_input_kind $ref $pin] eq $kind}] "D source policy: $ref/$pin"
}
sb::require [expr {[sb::family {pipe42/reg[24]}] eq {pipe42/reg[]}}] "Bus family"
sb::require [expr {[sb::family pipe42/copy_b43] eq {pipe42/copy_b#}}] "Scalar suffix family"
sb::require [expr {[sb::family pipe42/state_reg] eq {pipe42/state_reg}}] "Hierarchy must be preserved"
sb::require [expr {[sb::one_bit {} 1] == 1 && [sb::one_bit 1'b0 1] == 0}] "FDSE INIT default"
sb::require [expr {[sb::one_bit 1'h1] == 1 && [sb::one_bit false] == 0}] "Effective bit normalization"
sb::require [catch {sb::one_bit 1'bx}] "Reject X values"
sb::require [expr {[sb::ce_gain SLR1 SLR2 {SLR2} 33] == 33}] "Local CE avoids reverse crossing"
sb::require [expr {[sb::ce_gain SLR2 SLR1 {SLR2 SLR2 SLR2} 64] == 61}] "Input replication cost"
sb::require [expr {[sb::ce_gain SLR1 SLR2 {SLR0 SLR0} 2] == -2}] "Reject harmful localization"
set chunks [sb::chunks [lrepeat 400 pin] 99]
set lengths {}
foreach c $chunks {lappend lengths [llength $c]}
sb::require [expr {$lengths eq {99 99 99 99 4}}] "Fanout strictly below 100"
puts "PASS: family identity, FF defaults, CE cost, strict fanout chunking"
