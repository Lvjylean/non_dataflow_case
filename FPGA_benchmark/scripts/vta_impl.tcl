# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

set_param general.maxThreads 4
set root $::env(BENCH_ROOT)
set hls $::env(VTA_HLS_RUN)
source $hls/config.tcl
set inp_part $INP_MEM_BANKS
set inp_mem_width $INP_MEM_WIDTH
set inp_mem_depth $INP_MEM_DEPTH
set wgt_part $WGT_MEM_BANKS
set wgt_mem_width $WGT_MEM_WIDTH
set wgt_mem_depth $WGT_MEM_DEPTH
set out_part $OUT_MEM_BANKS
set out_mem_width $OUT_MEM_WIDTH
set out_mem_depth $OUT_MEM_DEPTH
set num_wgt_mem_uram 0
set device_family virtex-ultrascale+
proc binary_value {bits} {
 if {![regexp {^[01]+$} $bits]} {error "Invalid binary string"}
 set value 0
 foreach bit [split $bits ""] {set value [expr {2*$value+$bit}]}
 return $value
}
set axi_cache [binary_value $AXI_CACHE_BITS]
set axi_prot [binary_value $AXI_PROT_BITS]
create_project vta_project project -part xcu250-figd2104-2L-e
set repos {}
foreach stage {fetch load compute store} {lappend repos $hls/vta_$stage/soln/impl/ip}
set_property ip_repo_paths $repos [current_project]
update_ip_catalog
create_bd_design vta_core
proc init_fifo_property {fifo width_bytes depth} {
  set_property -dict [ list \
    CONFIG.FIFO_Implementation_rach {Common_Clock_Distributed_RAM} \
    CONFIG.FIFO_Implementation_wach {Common_Clock_Distributed_RAM} \
    CONFIG.FIFO_Implementation_wrch {Common_Clock_Distributed_RAM} \
    CONFIG.Full_Flags_Reset_Value {1} \
    CONFIG.INTERFACE_TYPE {AXI_STREAM} \
    CONFIG.Input_Depth_axis $depth \
    CONFIG.Reset_Type {Asynchronous_Reset} \
    CONFIG.TDATA_NUM_BYTES $width_bytes \
  ] $fifo
}

# Procedure to initialize BRAM
proc init_bram_property {bram width depth} {
  set_property -dict [ list \
    CONFIG.use_bram_block {Stand_Alone} \
    CONFIG.Assume_Synchronous_Clk {true} \
    CONFIG.Byte_Size {8} \
    CONFIG.Enable_32bit_Address {true} \
    CONFIG.Enable_B {Use_ENB_Pin} \
    CONFIG.Memory_Type {True_Dual_Port_RAM} \
    CONFIG.Read_Width_A $width \
    CONFIG.Read_Width_B $width \
    CONFIG.Register_PortA_Output_of_Memory_Primitives {false} \
    CONFIG.Register_PortB_Output_of_Memory_Primitives {false} \
    CONFIG.Use_Byte_Write_Enable {true} \
    CONFIG.Use_RSTA_Pin {true} \
    CONFIG.Use_RSTB_Pin {true} \
    CONFIG.Write_Depth_A $depth \
    CONFIG.Write_Width_A $width \
    CONFIG.Write_Width_B $width \
  ] $bram
}

# Create instance: axi_smc0, and set properties
set axi_smc0 [ create_bd_cell -type ip -vlnv xilinx.com:ip:smartconnect:1.0 axi_smc0 ]
set_property -dict [ list \
  CONFIG.NUM_MI {1} \
  CONFIG.NUM_SI {5} \
] $axi_smc0

# Create instance: axi_xbar, and set properties
set axi_xbar \
  [ create_bd_cell -type ip -vlnv xilinx.com:ip:axi_interconnect:2.1 axi_xbar ]
set_property -dict [ list \
  CONFIG.NUM_MI {8} \
  CONFIG.NUM_SI {1} \
] $axi_xbar

# Create instance: fetch_0, and set properties
set fetch_0 [ create_bd_cell -type ip -vlnv xilinx.com:hls:fetch:1.0 fetch_0 ]
set_property -dict [ list \
  CONFIG.C_M_AXI_INS_PORT_CACHE_VALUE $axi_cache \
  CONFIG.C_M_AXI_INS_PORT_PROT_VALUE $axi_prot \
] $fetch_0

# Create instance: load_0, and set properties
set load_0 [ create_bd_cell -type ip -vlnv xilinx.com:hls:load:1.0 load_0 ]
set_property -dict [ list \
  CONFIG.C_M_AXI_DATA_PORT_CACHE_VALUE $axi_cache \
  CONFIG.C_M_AXI_DATA_PORT_PROT_VALUE $axi_prot \
] $load_0

# Create instance: compute_0, and set properties
set compute_0 [ create_bd_cell -type ip -vlnv xilinx.com:hls:compute:1.0 compute_0 ]
set_property -dict [ list \
  CONFIG.C_M_AXI_DATA_PORT_CACHE_VALUE $axi_cache \
  CONFIG.C_M_AXI_DATA_PORT_PROT_VALUE $axi_prot \
  CONFIG.C_M_AXI_UOP_PORT_CACHE_VALUE $axi_cache \
  CONFIG.C_M_AXI_UOP_PORT_PROT_VALUE $axi_prot \
] $compute_0

# Create instance: store_0, and set properties
set store_0 [ create_bd_cell -type ip -vlnv xilinx.com:hls:store:1.0 store_0 ]
set_property -dict [ list \
  CONFIG.C_M_AXI_DATA_PORT_CACHE_VALUE $axi_cache \
  CONFIG.C_M_AXI_DATA_PORT_PROT_VALUE $axi_prot \
] $store_0

# Create command queues and set properties
set cmd_queue_list {load_queue gemm_queue store_queue}
foreach cmd_queue $cmd_queue_list {
  set tmp_cmd_queue [ create_bd_cell -type ip -vlnv xilinx.com:ip:fifo_generator:13.2 $cmd_queue ]
  # Width is 16B (128b, as set in hw_spec.h), depth is 512 (depth of FIFO on Zynq 7000 and Zynq Ultrascale+)
  # TODO: derive it from vta_config.h
  [ init_fifo_property $tmp_cmd_queue 16 512 ]
}

# Create dependence queues and set properties
set dep_queue_list {l2g_queue g2l_queue g2s_queue s2g_queue}
foreach dep_queue $dep_queue_list {
  set tmp_dep_queue [ create_bd_cell -type ip -vlnv xilinx.com:ip:fifo_generator:13.2 $dep_queue ]
  # Width is 1B (min width), depth is 1024
  # TODO: derive it from vta_config.h
  [ init_fifo_property $tmp_dep_queue 1 1024 ]
}

# Create and connect inp_mem partitions
for {set i 0} {$i < $inp_part} {incr i} {
  # Create instance: inp_mem, and set properties
  set inp_mem [ create_bd_cell -type ip -vlnv xilinx.com:ip:blk_mem_gen:8.4 inp_mem_${i} ]
  [ init_bram_property $inp_mem $inp_mem_width $inp_mem_depth ]
  # If module has more than 1 mem port, the naming convention changes
  if {$inp_part > 1} {
    set porta [get_bd_intf_pins load_0/inp_mem_${i}_PORTA]
    set portb [get_bd_intf_pins compute_0/inp_mem_${i}_PORTA]
  } else {
    set porta [get_bd_intf_pins load_0/inp_mem_PORTA]
    set portb [get_bd_intf_pins compute_0/inp_mem_PORTA]
  }
  # Create interface connections
  connect_bd_intf_net -intf_net load_0_inp_mem_PORTA \
    [get_bd_intf_pins $inp_mem/BRAM_PORTA] \
    $porta
  connect_bd_intf_net -intf_net compute_0_inp_mem_PORTA \
    [get_bd_intf_pins $inp_mem/BRAM_PORTB] \
    $portb
}

# Create and connect wgt_mem partitions
for {set i 0} {$i < $wgt_part} {incr i} {
  # Create instance: wgt_mem, and set properties
  set wgt_mem [ create_bd_cell -type ip -vlnv xilinx.com:ip:blk_mem_gen:8.4 wgt_mem_${i} ]
  [ init_bram_property $wgt_mem $wgt_mem_width $wgt_mem_depth ]
  # If module has more than 1 mem port, the naming convention changes
  if {$wgt_part > 1} {
    set porta [get_bd_intf_pins load_0/wgt_mem_${i}_PORTA]
    set portb [get_bd_intf_pins compute_0/wgt_mem_${i}_PORTA]
  } else {
    set porta [get_bd_intf_pins load_0/wgt_mem_PORTA]
    set portb [get_bd_intf_pins compute_0/wgt_mem_PORTA]
  }
  # Create interface connections
  connect_bd_intf_net -intf_net load_0_wgt_mem_${i}_PORTA \
    [get_bd_intf_pins $wgt_mem/BRAM_PORTA] \
    $porta
  connect_bd_intf_net -intf_net compute_0_wgt_mem_${i}_PORTA \
    [get_bd_intf_pins $wgt_mem/BRAM_PORTB] \
    $portb
  if { $device_family eq "zynq-ultrascale+" && $i < $num_wgt_mem_uram } {
    set_property -dict [list CONFIG.PRIM_type_to_Implement {URAM}] $wgt_mem
  }
}

# Create and connect out_mem partitions
for {set i 0} {$i < $out_part} {incr i} {
  # Create instance: out_mem, and set properties
  set out_mem [ create_bd_cell -type ip -vlnv xilinx.com:ip:blk_mem_gen:8.4 out_mem_${i} ]
  [ init_bram_property $out_mem $out_mem_width $out_mem_depth ]
  # If module has more than 1 mem port, the naming convention changes
  if {$out_part > 1} {
    set porta [get_bd_intf_pins compute_0/out_mem_${i}_PORTA]
    set portb [get_bd_intf_pins store_0/out_mem_${i}_PORTA]
  } else {
    set porta [get_bd_intf_pins compute_0/out_mem_PORTA]
    set portb [get_bd_intf_pins store_0/out_mem_PORTA]
  }
  # Create interface connections
  connect_bd_intf_net -intf_net compute_0_out_mem_${i}_PORTA \
    [get_bd_intf_pins $out_mem/BRAM_PORTA] \
    $porta
  connect_bd_intf_net -intf_net store_0_out_mem_${i}_PORTA \
    [get_bd_intf_pins $out_mem/BRAM_PORTB] \
    $portb
}

connect_bd_intf_net -intf_net axi_xbar_M00_AXI [get_bd_intf_pins axi_xbar/M00_AXI] [get_bd_intf_pins fetch_0/s_axi_CONTROL_BUS]
connect_bd_intf_net -intf_net axi_xbar_M01_AXI [get_bd_intf_pins axi_xbar/M01_AXI] [get_bd_intf_pins load_0/s_axi_CONTROL_BUS]
connect_bd_intf_net -intf_net axi_xbar_M02_AXI [get_bd_intf_pins axi_xbar/M02_AXI] [get_bd_intf_pins compute_0/s_axi_CONTROL_BUS]
connect_bd_intf_net -intf_net axi_xbar_M03_AXI [get_bd_intf_pins axi_xbar/M03_AXI] [get_bd_intf_pins store_0/s_axi_CONTROL_BUS]
connect_bd_intf_net -intf_net fetch_0_l2g_dep_queue_V [get_bd_intf_pins l2g_queue/S_AXIS] [get_bd_intf_pins load_0/l2g_dep_queue]
connect_bd_intf_net -intf_net fetch_0_load_queue_V_V [get_bd_intf_pins fetch_0/load_queue] [get_bd_intf_pins load_queue/S_AXIS]
connect_bd_intf_net -intf_net fetch_0_gemm_queue_V_V [get_bd_intf_pins fetch_0/gemm_queue] [get_bd_intf_pins gemm_queue/S_AXIS]
connect_bd_intf_net -intf_net fetch_0_store_queue_V_V [get_bd_intf_pins fetch_0/store_queue] [get_bd_intf_pins store_queue/S_AXIS]
connect_bd_intf_net -intf_net compute_0_g2l_dep_queue_V [get_bd_intf_pins compute_0/g2l_dep_queue] [get_bd_intf_pins g2l_queue/S_AXIS]
connect_bd_intf_net -intf_net compute_0_g2s_dep_queue_V [get_bd_intf_pins compute_0/g2s_dep_queue] [get_bd_intf_pins g2s_queue/S_AXIS]
connect_bd_intf_net -intf_net store_0_s2g_dep_queue_V [get_bd_intf_pins s2g_queue/S_AXIS] [get_bd_intf_pins store_0/s2g_dep_queue]
connect_bd_intf_net -intf_net load_queue_M_AXIS [get_bd_intf_pins load_0/load_queue] [get_bd_intf_pins load_queue/M_AXIS]
connect_bd_intf_net -intf_net gemm_queue_M_AXIS [get_bd_intf_pins compute_0/gemm_queue] [get_bd_intf_pins gemm_queue/M_AXIS]
connect_bd_intf_net -intf_net store_queue_M_AXIS [get_bd_intf_pins store_0/store_queue] [get_bd_intf_pins store_queue/M_AXIS]
connect_bd_intf_net -intf_net l2g_queue_M_AXIS [get_bd_intf_pins compute_0/l2g_dep_queue] [get_bd_intf_pins l2g_queue/M_AXIS]
connect_bd_intf_net -intf_net g2l_queue_M_AXIS [get_bd_intf_pins g2l_queue/M_AXIS] [get_bd_intf_pins load_0/g2l_dep_queue]
connect_bd_intf_net -intf_net g2s_queue_M_AXIS [get_bd_intf_pins g2s_queue/M_AXIS] [get_bd_intf_pins store_0/g2s_dep_queue]
connect_bd_intf_net -intf_net s2g_queue_M_AXIS [get_bd_intf_pins compute_0/s2g_dep_queue] [get_bd_intf_pins s2g_queue/M_AXIS]
connect_bd_intf_net -intf_net fetch_0_m_axi_ins_port [get_bd_intf_pins axi_smc0/S00_AXI] [get_bd_intf_pins fetch_0/m_axi_ins_port]
connect_bd_intf_net -intf_net load_0_m_axi_data_port [get_bd_intf_pins axi_smc0/S01_AXI] [get_bd_intf_pins load_0/m_axi_data_port]
connect_bd_intf_net -intf_net compute_0_m_axi_uop_port [get_bd_intf_pins axi_smc0/S02_AXI] [get_bd_intf_pins compute_0/m_axi_uop_port]
connect_bd_intf_net -intf_net compute_0_m_axi_data_port [get_bd_intf_pins axi_smc0/S03_AXI] [get_bd_intf_pins compute_0/m_axi_data_port]
connect_bd_intf_net -intf_net store_0_m_axi_data_port [get_bd_intf_pins axi_smc0/S04_AXI] [get_bd_intf_pins store_0/m_axi_data_port]

foreach {stage index} {fetch 4 load 5 compute 6 store 7} {
 connect_bd_intf_net [get_bd_intf_pins ${stage}_0/s_axi_control] [get_bd_intf_pins [format "axi_xbar/M%02d_AXI" $index]]
}
make_bd_intf_pins_external [get_bd_intf_pins axi_xbar/S00_AXI]
make_bd_intf_pins_external [get_bd_intf_pins axi_smc0/M00_AXI]
set clk [create_bd_port -dir I -type clk aclk]
set_property CONFIG.FREQ_HZ 100000000 $clk
set rst [create_bd_port -dir I -type rst aresetn]
set_property CONFIG.POLARITY ACTIVE_LOW $rst
set_property CONFIG.ASSOCIATED_RESET aresetn $clk
set_property CONFIG.ASSOCIATED_BUSIF {S00_AXI_0:M00_AXI_0} $clk
foreach pin [get_bd_pins -hier -filter {TYPE == clk}] {
 if {[llength [get_bd_nets -quiet -of_objects $pin]] == 0} {connect_bd_net $clk $pin}
}
foreach pin [get_bd_pins -hier -filter {TYPE == rst}] {
 if {[llength [get_bd_nets -quiet -of_objects $pin]] == 0} {
  if {[string match *aresetn $pin] || [string match *ARESETN $pin] || [string match *ap_rst_n $pin]} {connect_bd_net $rst $pin}
 }
}
assign_bd_address
validate_bd_design
save_bd_design
set bd [get_files */vta_core.bd]
set_property synth_checkpoint_mode None $bd
generate_target all $bd
set wrapper [make_wrapper -files $bd -top]
add_files -norecurse $wrapper
set_property top vta_core_wrapper [current_fileset]
update_compile_order -fileset sources_1
synth_design -top vta_core_wrapper -part xcu250-figd2104-2L-e -mode out_of_context
if {[llength [get_cells -hier -filter {IS_BLACKBOX == 1}]]} {error "Unresolved black boxes"}
if {[llength [get_clocks -quiet]] == 0} {create_clock -name core_clk -period 10 [get_ports aclk]}
set core_clock [get_clocks -of_objects [get_ports aclk]]
set_property HD.CLK_SRC BUFGCE_X0Y0 [get_ports aclk]
set_input_delay 1 -clock $core_clock [get_ports -filter {DIRECTION == IN && NAME != aclk}]
set_output_delay 1 -clock $core_clock [all_outputs]
write_checkpoint post_synth.dcp
report_utilization -hierarchical -file post_synth_utilization.rpt
opt_design
place_design
phys_opt_design
write_checkpoint post_place.dcp
route_design
write_checkpoint routed.dcp
source $root/scripts/reports.tcl
exit
