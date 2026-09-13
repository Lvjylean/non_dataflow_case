# TRTRS unchanged RTL baseline, Vivado 10 ns

Objective: synthesize, place and route the numerically checked trtrs_n1024_u512 without custom optimization. Part xcu250-figd2104-2L-e, Vivado 2023.2, four threads.

Server run: /Projects/jinyang/workspace/non_dataflow_crossSLR/case/experiment/vivado-trtrs-baseline-10ns-20260911-01
Baseline RTL: case/experiment/hls-nondataflow-scale-20260911-02/runs/trtrs_n1024_u512/hls/sol/syn/verilog. HLS originally targeted 5 ns; RTL and all three HLS floating-point IP definitions remain unchanged. C simulation checked all 2048 solution values, worst absolute error 1.6653345369377348e-16.

Reference: parent scripts/run_monolithic_hls_output.{sh,tcl}; reuse part, OOC synthesis, flatten_hierarchy none, no_iobuf and basic build ordering. Differences: top kernel_trtrs_0; generate three IPs from original emitted Tcl; 10 ns clock applied before synthesis; omit BOTH phys_opt_design calls; no SLR/pblock/LOC constraints, replication, pipeline changes, retiming or custom strategies. Default opt_design is retained as standard netlist preparation. Existing IP Speed_Optimized properties are original HLS configuration, not new tuning.

Only internal clock timing is constrained. This is an out-of-context kernel baseline, not an integrated board/platform implementation; AXI I/O timing is not modeled. Routing completion and meeting 10 ns are separately evaluated.

Locally authored inputs: experiment_inputs/vivado-trtrs-baseline-10ns-20260911-01. Remote command: RUN_DIR=<server run> bash inputs/run.sh. Source snapshot and hashes are created server-to-server; all DCP/IP/RTL remain on server. No existing experiment is overwritten and no Vivado process is terminated.

Success criteria: routed checkpoint created, zero routing errors/unrouted internal nets and unresolved blackboxes; inspect DRC and methodology; independently reopen DCP and reproduce route/timing reports. Report WNS/WHS, actual resource/SLR use, crossings and congestion, wall time/RSS. Timing failure is recorded without adding optimization.

Status: synthesis, placement and routing completed; independent reopen and repeated timing succeeded. See reports/vivado-trtrs-baseline-10ns-20260911-01/summary.md for final evidence.

Observation during placement: default place_design itself emits Physopt 32-81 replication messages for high-fanout nets (including sext_ln36_cast_reg). No explicit phys_opt_design or project custom optimization was invoked. This is a default-tool baseline, NOT a frozen-netlist/no-automatic-optimization experiment. Do not claim otherwise. Also opt_design includes default power optimization internally.

Synthesis: 396402 total LUT, 224014 FF, 1412 DSP, 512 URAM, 5 RAMB36; no unresolved blackboxes. Synth timing WNS +6.464 ns, WHS +0.045 ns, ap_clk 10.000 ns; not routed timing.

2026-09-11 source-directory migration: the current HLS source experiment is /Projects/jinyang/workspace/non_dataflow_crossSLR/case/experiment/trtrs_20260911_110300_v05. RTL is under hls/sol/syn/verilog. The independent Vivado inputs and all DCPs remain at their original paths with unchanged content. Historical source paths above are provenance only.
