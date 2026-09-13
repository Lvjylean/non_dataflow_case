# U250 AI FPGA benchmarks

Server root: `/Projects/jinyang/workspace/non_dataflow_crossSLR/case/FPGA_benchmark` on eda070.
Local editable mirror: this directory. Target: xcu250-figd2104-2L-e; Vivado/Vitis HLS 2023.2; Ubuntu 22.04.4 LTS. Initial clock: 10 ns.

- upstream/: pinned unchanged third-party inputs, identified in sources.json.
- scripts/: U250 adapters, edited locally and synchronized to the server.
- docs/experiments/: experiment objectives and acceptance.
- runs/: unique server-only generated projects and checkpoints.
- reports/: compact report snapshots, locally and on the server.

VTA retains the complete fetch/load/compute/store architecture, command/dependency queues and shared SRAM. CNNA reuses a CNN engine composed of concurrent SystemC streaming modules. Neither is fully sequential, and neither statically unfolds a complete neural network.

Preserved single-SLR baseline status (2026-09-13): both buffered04 cores are VERIFIED fully routed and independently reopened. Full-interface hold timing remains FAIL; internal register setup/hold passes. Both occupy SLR0 with zero SLL use. VTA 2023.2 HLS and upstream C simulation pass. CNNA source HLS fails at missing systemc.h; its physical baseline uses pinned upstream 2019.1 exported HDL. See [final results](reports/summary_zh.md).

Acceptance: complete core retained, no black boxes, ROUTED_FULLY=1, zero GAPS/PARTIAL/UNROUTED/CONFLICTS and route errors, reviewed DRC/methodology, independent checkpoint reopen, measured WNS/WHS, hierarchy/SLR resources, SLL, congestion, runtime/memory and archived compact reports. Routing and timing closure are separate statuses. OOC core results do not prove PCIe/XRT integration or board inference. Initial upstream scale does not guarantee cross-SLR occupancy.

## Reproduce on eda070

Run from the server benchmark root. Every command requires a fresh run ID; launchers refuse to reuse an existing directory.

```bash
bash scripts/run_hls.sh vta <new-vta-hls-id>
bash scripts/run_vta_csim.sh <new-vta-csim-id> <new-vta-hls-id>
bash scripts/run_buffered_source.sh <new-vta-physical-id> vta
bash scripts/run_buffered_source.sh <new-cnna-physical-id> cnna
bash scripts/run_final_audit.sh <new-vta-physical-id>
bash scripts/run_final_audit.sh <new-cnna-physical-id>
```

For long runs, use a separately named tmux session. After completion, run `bash scripts/sync_reports.sh` from the local mirror to retrieve text reports. `python3 scripts/summarize.py` validates the selected baseline IDs listed in that script. See [run registry](docs/runs.md), [architecture](docs/architecture.md), and [results](reports/index.md).

The selected defaults are for initial routing bring-up. Any new array size or frequency is a separate controlled experiment. Preserve failed attempts and record their cause; do not replace upstream source with locally patched copies.

The user-requested two-SLR variants are in progress: VTA64 single-engine scaling and CNNA6 multi-engine scaling with real U250 platform integration. See [experiment record](docs/experiments/dual-slr-20260913.md) and [integration decision](docs/decisions/0003-dual-slr-platform.md). Existing single-SLR results remain the accepted baseline, with a hashed copy under archives/baseline_single_slr_20260913. New platform runs must pass generated interface-contract audits before routing results can be accepted.

The selected buffered04 profiles include a real BUFG in the wrapper. Earlier external-buffer attempts are diagnostic history, not accepted final baselines. Current buffered runner uses the pinned HLS run and interface-stub paths recorded in its environment setup; preserve those inputs. Full-interface and internal-register timing are reported separately.

Checkpoint recovery now produces both U250 XCLBIN containers from corrected platform02 routed DCPs. See [recovery and independent verification](reports/recovery_summary_zh.md) for current acceptance, resource/timing evidence and exact server artifact paths. Runtime metadata and bitstream payload consistency are checked separately from full timing coverage and board execution.

Scaled recovery verification completed on 2026-09-13: both containers and all non-review physical checks pass; overall status is REVIEW_REQUIRED for platform clock/CDC/boundary findings. No final signoff or board execution is claimed.
