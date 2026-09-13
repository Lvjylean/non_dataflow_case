# Two-SLR physical and timing audit — 2026-09-13

SSH recovered. The existing queue started corrected runs vta64_platform_20260913_02 and cnna6_platform_20260913_02. Both are in placement at this snapshot; neither has final routed reports or an exit record. No duplicate compilation or process termination was performed. The previously proposed slr_api_probe_20260913_01 directory does not exist on the server; do not count that probe as executed.

## Measured diagnostic builds, not accepted functional benchmarks

The following are actual routed measurements from **superseded** vta64_platform_20260913_01 and cnna6_platform_20260913_01. Their DDR decode window is invalid for the selected banks. They cannot validate the corrected packages or be used as deliverable configurations. Accelerator hierarchy counts exclude the platform shell.

| Accelerator | SLR | LUT | FF | BRAM36 equivalent | DSP |
|---|---|---:|---:|---:|---:|
| VTA64, one engine | SLR2 | 42,657 | 24,636 | 595 | 1,803 |
| VTA64, one engine | SLR3 | 34,350 | 3,816 | 644 | 2,304 |
| CNNA6, engines 1–3 | SLR2 | 138,178 | 276,621 | 469.5 | 1,215 |
| CNNA6, engines 4–6 | SLR3 | 138,172 | 276,620 | 469.5 | 1,215 |

Both accelerator hierarchies have zero primitives in SLR0/SLR1. CNNA6 is explicitly multi-engine throughput scaling. Placement was constrained to SLR2/SLR3; this is not an unconstrained natural-placement result.

| Full-platform timing/routing | VTA64 old01 | CNNA6 old01 |
|---|---:|---:|
| Kernel clock, reported MHz | 100.010 | 100.010 |
| WNS, ns | +0.010 | +0.057 |
| WHS, ns | +0.009 | +0.009 |
| WPWS, ns | 0.000 | 0.000 |
| TNS / THS / TPWS, ns | 0 / 0 / 0 | 0 / 0 / 0 |
| Fully routed / routable nets | 525340 / 525340 | 1170261 / 1170261 |
| Unconstrained internal endpoints | 0 | 0 |
| No input delay ports | 10 | 10 |
| No output delay ports | 9 | 10 |

ROUTED_FULLY=1; routing errors, gaps, partial, unrouted and conflicts are zero. Reported final DRC errors/critical warnings and black boxes are zero. These facts are distinct from methodology results: both designs have critical clock-methodology warnings (TIMING-1/2/4/6/7/14/54), CDC warnings (TIMING-9/10), and missing boundary delays. TIMING-18 specifically identifies PCIe PERST and DDR reset outputs. These require platform-specific review; positive slack does not prove full timing coverage. No independent reopened-checkpoint acceptance is claimed for these old builds. The full-platform worst slack spans multiple clocks and is not a kernel Fmax measurement.

Evidence is synchronized under each run's physical/: accelerator_regions.tsv, per-kernel utilization.rpt, timing_summary.rpt, route_status.rpt, route_flags.tsv, methodology.rpt and cdc.rpt. Server artifacts remain under /Projects/jinyang/workspace/non_dataflow_crossSLR/case/FPGA_benchmark/runs/<run-id>; no DCP, bitstream or XCLBIN was copied locally.

## Corrected-build acceptance still pending

Corrected input packages vta64_package_20260913_03 and cnna_package_20260913_05 passed generated AXI address/reset audits. Both active runs include actual clocks, verbose check_timing, per-SLR DSP/BRAM counts and independent reopen hooks. scripts/validate_platform.py now also rejects incomplete timing coverage and unreviewed methodology warnings. Real old reports with positive slack were checked and remain PENDING_OR_FAILED.

Next: collect corrected postroute reports, compare reopened DCP reports and hashes, review every clock/CDC/boundary exception, and publish corrected SLR/timing measurements. Do not equate old measurements with current corrected results. No board execution has been verified.
