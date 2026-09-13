# ADR: complete-core OOC baseline before platform integration

Accepted within the user-requested U250 backend benchmark scope.

Build complete accelerator cores at upstream scale on xcu250-figd2104-2L-e using 10ns clock and 1ns external interface delays. Use external AXI/stream and clock/reset boundaries. Preserve VTA's four-module concurrency, FIFOs and SRAM, and CNNA's full cnn_top hierarchy. Do not add forced SLR partitioning or duplicate cores to manufacture a cross-SLR result.

VTA regenerates HLS IP in 2023.2 and passes upstream C simulation. CNNA uses pinned unchanged upstream 2019.1 exported HDL because the available HLS environment fails on systemc.h. Label this explicitly as a physical-only CNNA baseline. Preserve SystemC sources for a future compatible HLS toolchain.

Consequences: provides routed accelerator cores and comparable physical reports; does not provide xclbin, PCIe/DDR platform integration, board inference or CNNA source-regeneration proof. Routing, timing closure and numerical/board verification remain separate outcomes. Later scaling or shell integration must receive its own configuration and run ID.
