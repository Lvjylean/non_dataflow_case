set_param general.maxThreads 4
set root $::env(BENCH_ROOT)
set kind $::env(CORE_KIND)
set kernel ${kind}_kernel
if {$kind eq "vta64"} {
  # Reuse only the unchanged compute/interconnect construction, before OOC ports.
  set f [open $root/scripts/vta_build_bd.tcl r]; set code [read $f]; close $f
  set marker "make_bd_intf_pins_external"
  set pos [string first $marker $code]
  if {$pos < 0} {error "Missing VTA integration boundary"}
  eval [string range $code 0 [expr {$pos-1}]]
  set controls {}
  foreach stage {fetch load compute store} {lappend controls ${stage}_0/s_axi_CONTROL_BUS}
  foreach stage {fetch load compute store} {lappend controls ${stage}_0/s_axi_control}
  set memory_width 128
} else {
  create_project cnna_project project -part xcu250-figd2104-2L-e
  set_property ip_repo_paths [list $::env(CNNA_DMA_RUN)/cnna_dma_hls/soln/impl/ip] [current_project]
  update_ip_catalog
  set rtl $root/upstream/CNNA/reference_ip/hdl/verilog
  read_vhdl [glob $rtl/*.vhd]
  read_verilog [glob $rtl/*.v]
  update_compile_order -fileset sources_1
  create_bd_design cnna_core
  create_bd_cell -type module -reference cnn_top cnn_engine
  create_bd_cell -type ip -vlnv xilinx.com:hls:cnna_dma:1.0 dma
  create_bd_cell -type ip -vlnv xilinx.com:ip:axi_interconnect:2.1 axi_xbar
  set_property -dict [list CONFIG.NUM_MI 2 CONFIG.NUM_SI 1] [get_bd_cells axi_xbar]
  create_bd_cell -type ip -vlnv xilinx.com:ip:smartconnect:1.0 axi_smc0
  set_property -dict [list CONFIG.NUM_MI 1 CONFIG.NUM_SI 5] [get_bd_cells axi_smc0]
  foreach {a b} {sx X sw W sb BUF sc CTRL} {
    connect_bd_intf_net [get_bd_intf_pins dma/$a] [get_bd_intf_pins cnn_engine/S_AXIS_$b]
  }
  connect_bd_intf_net [get_bd_intf_pins dma/sy] [get_bd_intf_pins cnn_engine/M_AXIS_Y]
  set i 0
  foreach bus {mx mw mb mc my} {
    connect_bd_intf_net [get_bd_intf_pins dma/m_axi_$bus] [get_bd_intf_pins [format "axi_smc0/S%02d_AXI" $i]]
    incr i
  }
  set controls {dma/s_axi_control cnn_engine/s_axi_slv0}
  set i 0
  foreach bus $controls {
    connect_bd_intf_net [get_bd_intf_pins $bus] [get_bd_intf_pins [format "axi_xbar/M%02d_AXI" $i]]
    incr i
  }
  set memory_width 256
}
set ctrl [create_bd_intf_port -mode Slave -vlnv xilinx.com:interface:aximm_rtl:1.0 S_AXI_CONTROL]
set_property -dict [list CONFIG.PROTOCOL AXI4LITE CONFIG.ADDR_WIDTH 16 CONFIG.DATA_WIDTH 32 CONFIG.FREQ_HZ 100000000] $ctrl
create_bd_cell -type ip -vlnv xilinx.com:ip:axi_register_slice:2.1 control_slice
set_property -dict [list CONFIG.PROTOCOL AXI4LITE CONFIG.REG_AW 1 CONFIG.REG_W 1 CONFIG.REG_B 1 CONFIG.REG_AR 1 CONFIG.REG_R 1] [get_bd_cells control_slice]
connect_bd_intf_net $ctrl [get_bd_intf_pins control_slice/S_AXI]
connect_bd_intf_net [get_bd_intf_pins control_slice/M_AXI] [get_bd_intf_pins axi_xbar/S00_AXI]
set mem [create_bd_intf_port -mode Master -vlnv xilinx.com:interface:aximm_rtl:1.0 M_AXI_GMEM]
set_property -dict [list CONFIG.PROTOCOL AXI4 CONFIG.ADDR_WIDTH 64 CONFIG.DATA_WIDTH $memory_width CONFIG.FREQ_HZ 100000000] $mem
create_bd_cell -type ip -vlnv xilinx.com:ip:axi_register_slice:2.1 memory_slice
set_property -dict [list CONFIG.REG_AW 1 CONFIG.REG_W 1 CONFIG.REG_B 1 CONFIG.REG_AR 1 CONFIG.REG_R 1] [get_bd_cells memory_slice]
connect_bd_intf_net [get_bd_intf_pins axi_smc0/M00_AXI] [get_bd_intf_pins memory_slice/S_AXI]
connect_bd_intf_net [get_bd_intf_pins memory_slice/M_AXI] $mem
set clk [create_bd_port -dir I -type clk ap_clk]
set_property -dict [list CONFIG.FREQ_HZ 100000000 CONFIG.ASSOCIATED_BUSIF {S_AXI_CONTROL:M_AXI_GMEM} CONFIG.ASSOCIATED_RESET ap_rst_n] $clk
set rst [create_bd_port -dir I -type rst ap_rst_n]
set_property CONFIG.POLARITY ACTIVE_LOW $rst
create_bd_cell -type ip -vlnv xilinx.com:ip:proc_sys_reset:5.0 reset_sync
set_property CONFIG.C_AUX_RESET_HIGH 1 [get_bd_cells reset_sync]
create_bd_cell -type ip -vlnv xilinx.com:ip:xlconstant:1.1 one
create_bd_cell -type ip -vlnv xilinx.com:ip:xlconstant:1.1 zero
set_property CONFIG.CONST_VAL 0 [get_bd_cells zero]
connect_bd_net $rst [get_bd_pins reset_sync/ext_reset_in]
connect_bd_net [get_bd_pins one/dout] [get_bd_pins reset_sync/dcm_locked]
connect_bd_net [get_bd_pins zero/dout] [get_bd_pins reset_sync/aux_reset_in] [get_bd_pins reset_sync/mb_debug_sys_rst]
foreach pin [get_bd_pins -hier -filter {TYPE == clk && DIR == I}] {
  if {[llength [get_bd_nets -quiet -of_objects $pin]] == 0} {connect_bd_net $clk $pin}
}
foreach pin [get_bd_pins -hier -filter {TYPE == rst && DIR == I}] {
  if {[llength [get_bd_nets -quiet -of_objects $pin]] == 0} {
    if {[regexp -nocase {aresetn$|ap_rst_n$} $pin]} {
      connect_bd_net [get_bd_pins reset_sync/peripheral_aresetn] $pin
    } else {error "Unclassified reset input $pin"}
  }
}
assign_bd_address
set memory_segment [get_bd_addr_segs M_AXI_GMEM/Reg]
if {[llength $memory_segment] != 1} {error "Missing external DDR address segment"}
foreach space [get_bd_addr_spaces -hier] {
  if {[string match */Data_m_axi_* $space]} {
    assign_bd_address -force -offset 0x0000000000000000 -range 1T -target_address_space $space $memory_segment
  }
}
set idx 0
set mapfile [open address_map.tsv w]
puts $mapfile "interface\toffset\trange"
foreach bus $controls {
  set segs [get_bd_addr_segs -of_objects [get_bd_intf_pins $bus]]
  if {[llength $segs] != 1} {error "Ambiguous control address $bus: $segs"}
  assign_bd_address -force -offset [format 0x%08x [expr {$idx*4096}]] -range 4K -target_address_space [get_bd_addr_spaces S_AXI_CONTROL] $segs
  puts $mapfile "$bus\t[format 0x%08x [expr {$idx*4096}]]\t4096"
  incr idx
}
close $mapfile
validate_bd_design
save_bd_design
set bd [get_files */[current_bd_design].bd]
set_property synth_checkpoint_mode None $bd
generate_target all $bd
set wrapper [make_wrapper -files $bd -top]
add_files -norecurse $wrapper
set_property top [file rootname [file tail $wrapper]] [current_fileset]
update_compile_order -fileset sources_1
ipx::package_project -root_dir packaged -vendor benchmark.local -library rtl -taxonomy /KernelIP -import_files -set_current true
set core [ipx::current_core]
set_property name $kernel $core
set_property core_revision 1 $core
set_property sdx_kernel true $core
set_property sdx_kernel_type rtl $core
foreach bus {S_AXI_CONTROL M_AXI_GMEM} {ipx::associate_bus_interfaces -busif $bus -clock ap_clk $core}
ipx::create_xgui_files $core
ipx::update_checksums $core
ipx::check_integrity -kernel $core
ipx::save_core $core
set f [open kernel.xml w]
puts $f "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
puts $f "<root versionMajor=\"1\" versionMinor=\"6\"><kernel name=\"$kernel\" language=\"ip_c\" vlnv=\"benchmark.local:rtl:$kernel:1.0\" attributes=\"\" preferredWorkGroupSizeMultiple=\"0\" workGroupSize=\"1\" interrupt=\"false\" hwControlProtocol=\"user_managed\"><ports>"
puts $f "<port name=\"S_AXI_CONTROL\" mode=\"slave\" range=\"0x10000\" dataWidth=\"32\" portType=\"addressable\" base=\"0x0\"/>"
puts $f "<port name=\"M_AXI_GMEM\" mode=\"master\" range=\"0xFFFFFFFFFFFFFFFF\" dataWidth=\"$memory_width\" portType=\"addressable\" base=\"0x0\"/>"
puts $f "</ports><args>"
if {$kind eq "vta64"} {set args {insns 0x4010}} else {set args {x 0x10 w 0x1c buf 0x28 ctrl 0x34 y 0x40}}
set i 0
foreach {name offset} $args {
  puts $f "<arg name=\"$name\" addressQualifier=\"1\" id=\"$i\" port=\"M_AXI_GMEM\" size=\"0x8\" offset=\"$offset\" hostOffset=\"0x0\" hostSize=\"0x8\" type=\"void*\"/>"
  incr i
}
puts $f "</args></kernel></root>"
close $f
package_xo -xo_path ${kernel}.xo -kernel_name $kernel -ip_directory packaged -kernel_xml kernel.xml
exit
