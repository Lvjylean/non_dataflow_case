# TRTRS 10 ns default Vivado baseline

Server: eda070, /Projects/jinyang/workspace/non_dataflow_crossSLR/case/experiment/vivado-trtrs-baseline-10ns-20260911-01
Top kernel_trtrs_0; MAXN=1024, NCU=512, LDA=1024, LDB=2. Double-precision lower-triangular solve with two right-hand sides. Original HLS RTL targeted 5 ns and remains unchanged; Vivado 2023.2 targets xcu250-figd2104-2L-e at 10 ns.

Implementation completed successfully. All 657422 routable nets fully routed, zero routing errors and zero unresolved blackboxes. Formal routed timing: WNS +0.008217 ns, WHS +0.030000 ns, TNS/THS 0. Setup margin is only about 8 ps. Independent checkpoint reopen succeeded; repeated formal timing matches the original result. Final completion marker is checked separately in reopen/verified.txt and exit_code.txt.

| Resource | Total | SLR0 | SLR1 | SLR2 | SLR3 |
|---|---:|---:|---:|---:|---:|
| LUT | 389820 | 0 | 94745 | 234158 | 60917 |
| FF | 224316 | 0 | 54168 | 121818 | 48330 |
| DSP | 1412 | 0 | 352 | 629 | 431 |
| URAM | 512 | 0 | 128 | 192 | 192 |
| BRAM36 | 5 | 0 | 0 | 0 | 5 |

Three SLRs are used. SLR2 and SLR3 URAM use is 60% each; SLR2 CLB occupancy is 81.78%, while LUT utilization is 54.20%. Total LUTs equal 90.24% of one SLR capacity; total URAMs equal 160%. Resource-size requirement is met; these are actual physical results, not HLS estimates.

Cross-SLR boundary connections: SLR3–SLR2 11367 (49.34%); SLR2–SLR1 1603 (6.96%); SLR1–SLR0 zero. Sum 12970 counts boundary crossings, not necessarily unique nets. No TX/RX Laguna registers used. Placer final congestion level 5, router initial global/short congestion level 5, estimated timing congestion level 6. Initial localized SLL demand reaches 119%; final routing nevertheless succeeded. The congestion report includes SLR net crossing tables. A separate attempted -slr_crossing option is unsupported and caught; its diagnostic is retained. Valid crossing evidence comes from utilization.rpt, congestion.rpt and timing paths.

All worst 100 reported setup paths cross SLRs (102 crossing-net occurrences; not an exhaustive timing-path census). Worst path: AXI gmem1 read buffer RAMB36 to matB_214_1_reg[25], SLR3→SLR2. gmem1_RDATA[25] has fanout 1024 and entire crossing-net delay 8.923 ns. Path delay 9.923 ns, including total route delay 8.981 ns (90.507%). No optimization was applied to address this.

No custom optimization, SLR/pblock/LOC constraints, RTL edits, extra pipeline, retiming directive, or explicit phys_opt_design was used. Default synth_design, opt_design, place_design and route_design retain Vivado's built-in optimization, including default placer replication and LUT combining. This is a default-tool baseline, not a frozen-netlist experiment. Original HLS floating-point IP settings are unchanged.

DRC: zero Error/Critical Warning; 5009 warnings (2696 DPIP-2, 1284 DPOP-3, 1028 DPOP-4, 1 RTSTAT-10) and 2048 advisory items. Methodology: 527 TIMING-18 warnings for absent interface delays. OOC/no_iobuf, only ap_clk constrained; external AXI/reset timing and physical platform integration are not validated. No RTL cosimulation or board execution was performed. Prior C simulation checks all 2048 solution values and passed.

Main process wall time 1:21:22, maximum RSS 16433084 KiB (~15.67 GiB); place_design 26:43 and route_design 20:02. DCPs and generated hardware remain only on server. Routed DCP SHA256 c11213c862f037ff49dfd125e3cb07d14a9a2e2d3fa90d91903dbec5a18b1d32. Original 20 RTL/IP files rehashed unchanged.

Final verification: implementation and independent reopen both exited 0; reopen/verified.txt exists. Route status is identical before and after reopen, repeated DRC Error/Critical Warning and blackboxes are zero. Local executable inputs match server SHA256 values.

2026-09-11 source-directory migration: the current HLS source experiment is /Projects/jinyang/workspace/non_dataflow_crossSLR/case/experiment/trtrs_20260911_110300_v05. RTL is under hls/sol/syn/verilog. The independent Vivado inputs and all DCPs remain at their original paths with unchanged content. Historical source paths above are provenance only.
