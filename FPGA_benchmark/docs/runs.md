# Run registry

All paths below are relative to the server benchmark `runs/` directory. Existing attempts are preserved.

| Run | Purpose / interpretation |
|---|---|
| vta_hls_20260913_01 | Configuration import failure before HLS; original tmux stderr was not captured. Corrected in attempt02. |
| vta_hls_20260913_02 | Four-stage U250 HLS PASS; shared generated IP input for all VTA physical attempts. |
| vta_csim_20260913_01 | Upstream ALU/blocked GEMM C simulation PASS, zero errors. |
| cnna_hls_probe_20260913_01 | HLS fails at missing systemc.h; not a successful source-to-RTL build. |
| cnna_rtl_u250_20260913_01 | Selected CNNA physical baseline; unchanged upstream 2019.1 HDL, 10ns U250 OOC. |
| vta_u250_20260913_01 | Preserved first physical attempt. AXI cache string was interpreted as decimal, producing value7 rather than intended15. Not the selected baseline. |
| vta_u250_20260913_02 | Stops before design creation: scan %b unsupported by bundled Tcl. |
| vta_u250_20260913_03 | Selected corrected VTA physical baseline; same HLS IPs, explicit binary-value decoding. |

See reports/index.md and results.json for measured acceptance. No DCP or raw build state is stored locally.

## Final clock-complete profiles

| Run suffix | Interpretation |
|---|---|
| cnna_buffered_u250_20260913_01 / vta_buffered_u250_20260913_01 | Stub parser failed before core implementation; preserved. |
| cnna_buffered_u250_20260913_02 / vta_buffered_u250_20260913_02 | Wrapper synthesized, DCP submodule import failed before placement. |
| cnna_buffered_u250_20260913_03 / vta_buffered_u250_20260913_03 | Explicit wrapper reopen did not resolve DCP import; failed before placement. |
| cnna_buffered_u250_20260913_04 / vta_buffered_u250_20260913_04 | Selected direct-HDL synthesis profiles with one real BUFG; see current validation.json for acceptance. |

The slow old CNNA physical_audit was terminated with explicit approval of PID2789887; exit143 and unchanged DCP hashes are archived. Final profiles use run_final_audit.sh and bulk-vector aggregation instead.

## 2026-09-13 corrected platform recovery

| Run | Role and interpretation |
|---|---|
| vta64_platform_20260913_02 / cnna6_platform_20260913_02 | Corrected routed input DCPs; postroute hook failed on unsupported redirect; preserve raw failure. |
| vta64_recovery_20260913_01 / cnna6_recovery_20260913_01 | Native bitgen succeeds; fresh reuse lacks address_map.xml at rtdgen. Full reports and independent reopen stored separately. |
| vta64_container_20260913_01 / cnna6_container_20260913_01 | Selected XCLBINs: native address conversion and runtime-section assembly; metadata/payload checks pass. |
| vta64_resource_review_20260913_01 | Additional independent native per-SLR utilization and detailed CDC audit, with unchanged DCP hashes. |
| vta64_packaging_20260913_01 | Superseded failed attempt: relocated --from_step invalidated VPL state and re-entered project generation; exited naturally. Do not reuse this method. |

All run roots are /Projects/jinyang/workspace/non_dataflow_crossSLR/case/FPGA_benchmark/runs/<run-id> on eda070. See reports/recovery_summary_zh.md for measured acceptance; no board execution is claimed.
