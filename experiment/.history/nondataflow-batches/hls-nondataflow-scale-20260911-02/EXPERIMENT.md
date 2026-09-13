# Extended resource screening

Server: /Projects/jinyang/workspace/non_dataflow_crossSLR/case/experiment/hls-nondataflow-scale-20260911-02
Baseline: batch 01 defaults and 256/32, 256/128 grid. QR at 256/128 measured 428235 LUT and 2187 DSP; inversion at 256/32 measured 225633 LUT.
Objective: seek three to four SLR resource equivalents with 1024 matrix dimension and NCU=512. Cases: getrf, getrf_nopivot, geqrf, gematrixinverse, trtrs.
Controlled exploratory interaction of dimension and parallelism; no causal one-factor claim. Same headers, 5ns target, part and Vitis 2023.2 as batch01. Local editable inputs under experiment_inputs/hls-nondataflow-scale-20260911-02.
One additional worker, at most four HLS tasks including batch01 on the 20-core, 125-GiB server. Retain all failures and oversize results. Same resource acceptance and validation limitations as batch01. Synchronize reports locally on completion. No physical run or DCP.

Runtime budget: 900 seconds per HLS trial. An external watchdog selects only this batch run-directory processes owned by this user, refuses Vivado, records timeout metadata, and terminates overdue HLS work. Timeouts are inconclusive, not resource failures.

## Final outcome

Attempted: 5; generated RTL: 4; qualified after resource/known-validity screening: 3.

States: COMPLETE=4, FAILED=0, TIMED_OUT=0, CANCELLED=1, RUNNING=0.

Server: `/Projects/jinyang/workspace/non_dataflow_crossSLR/case/experiment/hls-nondataflow-scale-20260911-02`. See [combined report](../hls-nondataflow-summary.md) and `rtl_audit.json`.

All completed output directories and input hashes audited. All resource/XML totals and target capacity cross-checked. No physical implementation, DCP, routed timing, or C/RTL cosimulation produced. Numerical tests and invalid-parameter exclusions are in the combined report.
