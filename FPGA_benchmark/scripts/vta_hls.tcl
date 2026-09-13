set root_dir $::env(BENCH_ROOT)/upstream/tvm-vta
source config.tcl
set cflags $CFLAGS
set ::device $FPGA_DEVICE
set ::period $FPGA_PERIOD
foreach kind {inp wgt out} {
 set ::${kind}_reshape_factor [set [string toupper $kind]_MEM_AXI_RATIO]
 set ::${kind}_partition_factor [set [string toupper $kind]_MEM_BANKS]
}
proc init_design {} {

    # Set device id
    set_part $::device

    # Set the clock frequency
    create_clock -period $::period -name default

    # HLS pragmas to reshape/partition the input memory read/write port
    set_directive_array_reshape -type block -factor $::inp_reshape_factor -dim 2 "load" inp_mem
    set_directive_array_reshape -type block -factor $::inp_reshape_factor -dim 2 "compute" inp_mem
    if {$::inp_partition_factor > 1} {
        set_directive_array_partition -type block -factor $::inp_partition_factor -dim 2 "load" inp_mem
        set_directive_array_partition -type block -factor $::inp_partition_factor -dim 2 "compute" inp_mem
    }
    # HLS pragmas to reshape/partition the weight memory read/write port
    set_directive_array_reshape -type block -factor $::wgt_reshape_factor -dim 2 "load" wgt_mem
    set_directive_array_reshape -type block -factor $::wgt_reshape_factor -dim 2 "compute" wgt_mem
    if {$::wgt_partition_factor >1} {
        set_directive_array_partition -type block -factor $::wgt_partition_factor -dim 2 "load" wgt_mem
        set_directive_array_partition -type block -factor $::wgt_partition_factor -dim 2 "compute" wgt_mem
    }
    # HLS pragmas to reshape/partition the output memory read/write port
    set_directive_array_reshape -type block -factor $::out_reshape_factor -dim 2 "compute" out_mem
    set_directive_array_reshape -type block -factor $::out_reshape_factor -dim 2 "store" out_mem
    if {$::out_partition_factor > 1} {
        set_directive_array_partition -type block -factor $::out_partition_factor -dim 2 "compute" out_mem
        set_directive_array_partition -type block -factor $::out_partition_factor -dim 2 "store" out_mem
    }
}


foreach stage {fetch load compute store} {
 open_project vta_$stage
 set_top $stage
 add_files $root_dir/hardware/xilinx/src/vta.cc -cflags $cflags
 open_solution soln -flow_target vivado
 init_design
 csynth_design
 export_design -format ip_catalog
 close_project
}
exit
