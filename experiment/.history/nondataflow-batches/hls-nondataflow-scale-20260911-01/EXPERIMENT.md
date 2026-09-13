# Batch HLS non-dataflow resource screening

User authorization: generate Verilog under case/experiment, enlarge case parameters, identify designs reaching approximately 60% of one U250 SLR, preferably 3–4 SLR scale.

Server path: /Projects/jinyang/workspace/non_dataflow_crossSLR/case/experiment/hls-nondataflow-scale-20260911-01
Local editable inputs: experiment_inputs/hls-nondataflow-scale-20260911-01/
Baseline: each original case's default dimensions/parallelism; tool flow fixed to Vitis HLS 2023.2, Vivado IP target, xcu250-figd2104-2L-e, 5 ns clock. This is not a comparison with the separate existing GEMM physical experiments.

Design: exploratory parameter interaction grid of matrix dimension and compute-unit count (documented joint changes, not a one-factor causal claim). Matrix leading dimensions and AXI depth metadata track the new size. RSA changes operand width only; exponent remains 20 bits. No replicated dummy workloads or removed DATAFLOW pragmas. All library headers copied unchanged from source revision 3ab1ecd20. Original server library remains untouched.

Candidates: getrf, getrf_nopivot, geqrf, gematrixinverse, trtrs, gesvdj, gtsv, rsa. Defaults followed by larger parameter variants in manifest.json. Up to three concurrent processes. Stop scaling a family after failure, device oversize, or >=2.4 SLR compute resource equivalents; retain all failed runs. HLS csynth_design generates Verilog; no place/route, DCP, bitstream, or physical timing signoff is requested here.

Acceptance: XML and generated Verilog must exist, HLS return code zero. Compute criterion max(LUT/432000, FF/864000, DSP/3072)>=0.60, and no resource exceeds four SLR capacity. Storage-only candidates are separate. BRAM_18K denominator 1344 (672 BRAM36), URAM denominator 320. Resource fractions are separate, never summed. Three/four SLR equivalents do not prove actual SLR occupation or fit.

Validation: source/manifest inspection, Python syntax validation, HLS synthesis, result/XML/RTL cross-check. Numerical C simulation and RTL co-simulation remain separate validation gaps. Source parameter scaling intentionally changes problem size and latency, as authorized. Library/tool compatibility failures are retained as failures, not successful candidates.

Commands: synchronize editable snapshot to unique server directory; bash launch.sh; retrieve only report/XML/log/timing/status files to reports/hls-nondataflow-scale-20260911-01/. No DCP or generated RTL copied locally.

Runtime budget: 900 seconds per HLS trial. An external watchdog selects only this batch run-directory processes owned by this user, refuses Vivado, records timeout metadata, and terminates overdue HLS work. Timeouts are inconclusive, not resource failures.

## Final outcome

Attempted: 30; generated RTL: 27; qualified after resource/known-validity screening: 4.

States: COMPLETE=27, FAILED=1, TIMED_OUT=1, CANCELLED=1, RUNNING=0.

Server: `/Projects/jinyang/workspace/non_dataflow_crossSLR/case/experiment/hls-nondataflow-scale-20260911-01`. See [combined report](../hls-nondataflow-summary.md) and `rtl_audit.json`.

All completed output directories and input hashes audited. All resource/XML totals and target capacity cross-checked. No physical implementation, DCP, routed timing, or C/RTL cosimulation produced. Numerical tests and invalid-parameter exclusions are in the combined report.
