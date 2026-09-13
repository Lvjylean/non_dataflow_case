# Architecture and interpretation

## VTA

Pinned Apache VTA Xilinx HLS implementation. Four separately synthesized IPs: fetch, load, compute (GEMM and ALU plus accumulator/uop storage), store. One core executes successive instruction programs/layers.

The U250 wrapper preserves three 128-bit command FIFOs (depth 512), four dependence FIFOs (one-byte AXI-stream payload, depth 1024), input SRAM, two weight SRAM banks and output SRAM using upstream configuration-derived widths/depths. Eight AXI-Lite slave interfaces in Vitis HLS 2023.2 are all connected to an 8-way control interconnect. Five memory master interfaces share a SmartConnect output. External clock/reset replace the Zynq processing system and its PLL; the final U250 wrapper includes a real BUFG to implement the global clock tree. No static whole-network pipeline, no added compute pipeline, no forced SLR partition.

The HLS TARGET=ultra96 macro selects the upstream 128-bit bus/configuration conventions; the actual HLS and Vivado part is explicitly U250. It does not mean the generated design targets Ultra96. Runtime register mapping must be obtained from this generated block design; the old PYNQ host driver is not a U250 runtime.

C simulation executes the upstream software scheduling harness and validates ALU/blocked GEMM numerical results. It does not exercise AXI transaction timing or the assembled block design. RTL-system simulation and board runtime remain separate work.

## CNNA

Original SystemC source plus unchanged exported 2019.1 IP HDL from the pinned archive identified in sources.json. The routed top is cnn_top, including AXI stream and AXI-Lite wrappers, cnn control and p_top_cnn. Input, weights, intermediate buffer and control streams feed a reusable CNN engine; outputs return on AXI stream. Concurrent SystemC processes and streaming submodules are intrinsic to this core.

The archived HDL carries its own configuration and generated metadata; it must not be equated to the current SystemC source defaults or the probe flags without regeneration/equivalence evidence. Its original HLS part and 5ns target are historical metadata; the new physical target is U250 at 10ns. The available 2023.2 HLS invocation fails at missing systemc.h, so current results cannot claim source-to-RTL regeneration or new C/RTL verification.

## Physical boundary

Both implementations are out-of-context accelerator cores with external clock, control and memory/stream interfaces and an internal BUFG. Boundary input/output delay is 1ns; the clock is 10ns. No PCIe shell, DDR controller, XRT executable or board bitstream is included. DCP routing acceptance and nonnegative setup/hold slack are reported separately. Default-sized cores are baseline bring-up cases; measured SLR occupancy determines whether a later scale experiment is needed for cross-SLR research.

## Scaled platform variants

The preceding OOC boundary describes the preserved single-SLR baselines. VTA64 and CNNA6 instead integrate the installed U250 PCIe/DDR platform, synchronized resets and registered AXI interfaces as specified in ADR0003. Corrected platform02 DCPs are reused for bitstream generation; same-source address maps and native cf2sw/xclbinutil produce the recovered XCLBINs. Optional IDE SYSTEM_METADATA diagrams are omitted from these recovered containers; runtime sections are retained and checked. Physical consistency, numerical timing, constraint/CDC review and board execution have distinct acceptance states. See reports/recovery_summary_zh.md and docs/experiments/platform-recovery-20260913.md.
