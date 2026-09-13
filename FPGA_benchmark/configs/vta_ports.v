// Copyright 1986-2022 Xilinx, Inc. All Rights Reserved.
// Copyright 2022-2023 Advanced Micro Devices, Inc. All Rights Reserved.
// --------------------------------------------------------------------------------
// Tool Version: Vivado v.2023.2 (lin64) Build 4029153 Fri Oct 13 20:13:54 MDT 2023
// Date        : Sun Sep 13 00:55:10 2026
// Host        : ee4e070 running 64-bit Ubuntu 22.04.4 LTS
// Command     : write_verilog -mode synth_stub core_stub.v
// Design      : vta_core_wrapper
// Purpose     : Stub declaration of top-level module interface
// Device      : xcu250-figd2104-2L-e
// --------------------------------------------------------------------------------

// This empty module with port declaration file causes synthesis tools to infer a black box for IP.
// The synthesis directives are for Synopsys Synplify support to prevent IO buffer insertion.
// Please paste the declaration into a Verilog source file or add the file as an additional source.
module vta_core_wrapper(M00_AXI_0_araddr, M00_AXI_0_arburst, 
  M00_AXI_0_arcache, M00_AXI_0_arlen, M00_AXI_0_arlock, M00_AXI_0_arprot, M00_AXI_0_arqos, 
  M00_AXI_0_arready, M00_AXI_0_arsize, M00_AXI_0_arvalid, M00_AXI_0_awaddr, 
  M00_AXI_0_awburst, M00_AXI_0_awcache, M00_AXI_0_awlen, M00_AXI_0_awlock, 
  M00_AXI_0_awprot, M00_AXI_0_awqos, M00_AXI_0_awready, M00_AXI_0_awsize, 
  M00_AXI_0_awvalid, M00_AXI_0_bready, M00_AXI_0_bresp, M00_AXI_0_bvalid, M00_AXI_0_rdata, 
  M00_AXI_0_rlast, M00_AXI_0_rready, M00_AXI_0_rresp, M00_AXI_0_rvalid, M00_AXI_0_wdata, 
  M00_AXI_0_wlast, M00_AXI_0_wready, M00_AXI_0_wstrb, M00_AXI_0_wvalid, S00_AXI_0_araddr, 
  S00_AXI_0_arburst, S00_AXI_0_arcache, S00_AXI_0_arlen, S00_AXI_0_arlock, 
  S00_AXI_0_arprot, S00_AXI_0_arqos, S00_AXI_0_arready, S00_AXI_0_arregion, 
  S00_AXI_0_arsize, S00_AXI_0_arvalid, S00_AXI_0_awaddr, S00_AXI_0_awburst, 
  S00_AXI_0_awcache, S00_AXI_0_awlen, S00_AXI_0_awlock, S00_AXI_0_awprot, S00_AXI_0_awqos, 
  S00_AXI_0_awready, S00_AXI_0_awregion, S00_AXI_0_awsize, S00_AXI_0_awvalid, 
  S00_AXI_0_bready, S00_AXI_0_bresp, S00_AXI_0_bvalid, S00_AXI_0_rdata, S00_AXI_0_rlast, 
  S00_AXI_0_rready, S00_AXI_0_rresp, S00_AXI_0_rvalid, S00_AXI_0_wdata, S00_AXI_0_wlast, 
  S00_AXI_0_wready, S00_AXI_0_wstrb, S00_AXI_0_wvalid, aclk, aresetn)
/* synthesis syn_black_box black_box_pad_pin="M00_AXI_0_araddr[31:0],M00_AXI_0_arburst[1:0],M00_AXI_0_arcache[3:0],M00_AXI_0_arlen[7:0],M00_AXI_0_arlock[0:0],M00_AXI_0_arprot[2:0],M00_AXI_0_arqos[3:0],M00_AXI_0_arready,M00_AXI_0_arsize[2:0],M00_AXI_0_arvalid,M00_AXI_0_awaddr[31:0],M00_AXI_0_awburst[1:0],M00_AXI_0_awcache[3:0],M00_AXI_0_awlen[7:0],M00_AXI_0_awlock[0:0],M00_AXI_0_awprot[2:0],M00_AXI_0_awqos[3:0],M00_AXI_0_awready,M00_AXI_0_awsize[2:0],M00_AXI_0_awvalid,M00_AXI_0_bready,M00_AXI_0_bresp[1:0],M00_AXI_0_bvalid,M00_AXI_0_rdata[31:0],M00_AXI_0_rlast,M00_AXI_0_rready,M00_AXI_0_rresp[1:0],M00_AXI_0_rvalid,M00_AXI_0_wdata[31:0],M00_AXI_0_wlast,M00_AXI_0_wready,M00_AXI_0_wstrb[3:0],M00_AXI_0_wvalid,S00_AXI_0_araddr[31:0],S00_AXI_0_arburst[1:0],S00_AXI_0_arcache[3:0],S00_AXI_0_arlen[7:0],S00_AXI_0_arlock[0:0],S00_AXI_0_arprot[2:0],S00_AXI_0_arqos[3:0],S00_AXI_0_arready,S00_AXI_0_arregion[3:0],S00_AXI_0_arsize[2:0],S00_AXI_0_arvalid,S00_AXI_0_awaddr[31:0],S00_AXI_0_awburst[1:0],S00_AXI_0_awcache[3:0],S00_AXI_0_awlen[7:0],S00_AXI_0_awlock[0:0],S00_AXI_0_awprot[2:0],S00_AXI_0_awqos[3:0],S00_AXI_0_awready,S00_AXI_0_awregion[3:0],S00_AXI_0_awsize[2:0],S00_AXI_0_awvalid,S00_AXI_0_bready,S00_AXI_0_bresp[1:0],S00_AXI_0_bvalid,S00_AXI_0_rdata[31:0],S00_AXI_0_rlast,S00_AXI_0_rready,S00_AXI_0_rresp[1:0],S00_AXI_0_rvalid,S00_AXI_0_wdata[31:0],S00_AXI_0_wlast,S00_AXI_0_wready,S00_AXI_0_wstrb[3:0],S00_AXI_0_wvalid,aresetn" */
/* synthesis syn_force_seq_prim="aclk" */;
  output [31:0]M00_AXI_0_araddr;
  output [1:0]M00_AXI_0_arburst;
  output [3:0]M00_AXI_0_arcache;
  output [7:0]M00_AXI_0_arlen;
  output [0:0]M00_AXI_0_arlock;
  output [2:0]M00_AXI_0_arprot;
  output [3:0]M00_AXI_0_arqos;
  input M00_AXI_0_arready;
  output [2:0]M00_AXI_0_arsize;
  output M00_AXI_0_arvalid;
  output [31:0]M00_AXI_0_awaddr;
  output [1:0]M00_AXI_0_awburst;
  output [3:0]M00_AXI_0_awcache;
  output [7:0]M00_AXI_0_awlen;
  output [0:0]M00_AXI_0_awlock;
  output [2:0]M00_AXI_0_awprot;
  output [3:0]M00_AXI_0_awqos;
  input M00_AXI_0_awready;
  output [2:0]M00_AXI_0_awsize;
  output M00_AXI_0_awvalid;
  output M00_AXI_0_bready;
  input [1:0]M00_AXI_0_bresp;
  input M00_AXI_0_bvalid;
  input [31:0]M00_AXI_0_rdata;
  input M00_AXI_0_rlast;
  output M00_AXI_0_rready;
  input [1:0]M00_AXI_0_rresp;
  input M00_AXI_0_rvalid;
  output [31:0]M00_AXI_0_wdata;
  output M00_AXI_0_wlast;
  input M00_AXI_0_wready;
  output [3:0]M00_AXI_0_wstrb;
  output M00_AXI_0_wvalid;
  input [31:0]S00_AXI_0_araddr;
  input [1:0]S00_AXI_0_arburst;
  input [3:0]S00_AXI_0_arcache;
  input [7:0]S00_AXI_0_arlen;
  input [0:0]S00_AXI_0_arlock;
  input [2:0]S00_AXI_0_arprot;
  input [3:0]S00_AXI_0_arqos;
  output S00_AXI_0_arready;
  input [3:0]S00_AXI_0_arregion;
  input [2:0]S00_AXI_0_arsize;
  input S00_AXI_0_arvalid;
  input [31:0]S00_AXI_0_awaddr;
  input [1:0]S00_AXI_0_awburst;
  input [3:0]S00_AXI_0_awcache;
  input [7:0]S00_AXI_0_awlen;
  input [0:0]S00_AXI_0_awlock;
  input [2:0]S00_AXI_0_awprot;
  input [3:0]S00_AXI_0_awqos;
  output S00_AXI_0_awready;
  input [3:0]S00_AXI_0_awregion;
  input [2:0]S00_AXI_0_awsize;
  input S00_AXI_0_awvalid;
  input S00_AXI_0_bready;
  output [1:0]S00_AXI_0_bresp;
  output S00_AXI_0_bvalid;
  output [31:0]S00_AXI_0_rdata;
  output S00_AXI_0_rlast;
  input S00_AXI_0_rready;
  output [1:0]S00_AXI_0_rresp;
  output S00_AXI_0_rvalid;
  input [31:0]S00_AXI_0_wdata;
  input S00_AXI_0_wlast;
  output S00_AXI_0_wready;
  input [3:0]S00_AXI_0_wstrb;
  input S00_AXI_0_wvalid;
  input aclk /* synthesis syn_isclock = 1 */;
  input aresetn;
endmodule
