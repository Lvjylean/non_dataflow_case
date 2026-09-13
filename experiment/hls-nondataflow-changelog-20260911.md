# Change log

## 2026-09-11 — Batch non-dataflow HLS resource screening
- Added experiment_inputs/hls-nondataflow-scale-20260911-01, docs/experiments/hls-nondataflow-scale-20260911-01.md, reports snapshot/index, and HANDODD.md.
- Reason: user-requested Verilog generation and U250 SLR resource-scale selection.
- Behavior/timing: parameter variants change dimensions/parallelism or RSA width and therefore latency; original library sources unchanged. No physical optimization applied.
- Validation: input inspection and Python syntax check; server HLS and result checks in progress.
- Limitations: HLS estimates do not prove physical fit, crossing, timing, or numerical correctness.

## 2026-09-11 — Extended size grid
- Added batch02 input snapshot and experiment record to seek three/four-SLR resource scale; one additional worker.
- Baseline from batch01 HLS results. Dimension/parallelism and latency change; original library unchanged.
- Validated source presence, JSON and hashes; HLS results pending; physical fit and numerical validation remain unproven.

## 2026-09-11 — Bounded screening and report audit
- Added scripts/hls_trial_watchdog.py and scripts/summarize_hls_batches.py; updated both experiment records.
- Reason: bound pathological HLS compile scaling and independently verify XML capacity/resource totals.
- Impact: 900-second per-trial execution budget only; no source/RTL change. Timeout is inconclusive. No Vivado process may be stopped.
- Validation: Python AST parsing and summary audit against synchronized HLS XML passed. Physical/numerical checks remain outside this screening run.

## 2026-09-11 — RTL output integrity audit
- Added scripts/audit_server_hls_rtl.py, compact HLS snapshots, and aggregate report generation.
- Validation: batch01 initial 22 RTL directories and batch02 initial LU RTL passed top-module/file count checks; all 112/86 input hashes match. HLS XML part/capacity/resource totals agree.
- No behavioral change; final coverage will be refreshed when both batches are terminal.

## 2026-09-11 — QR capacity correction
- Added batch03 inputs and experiment record after measured 5768 BRAM18K exceeded U250 capacity in QR 1024/512.
- Reduced dimension/parallelism to 768/384; behavior covers a smaller matrix and different latency. Original source unchanged.
- Validation: parameter/source/manifest inspection; HLS pending. This is a capacity search, not a physical-fit claim.

## 2026-09-11 — Parameter domain and sampled numerical validation
- Added sampled C simulation inputs/record for four scaled kernels. Added SVD NCU32 exclusion due to fixed tmp[16] indexing in upstream implementation.
- No kernel/RTL behavior changes; generated invalid SVD variant retained but excluded.
- Validation pending server csim; samples do not replace exhaustive testing or C/RTL cosimulation.

## 2026-09-11 — Inverse failure diagnostic
- Added validation02 and experiment record for baseline/scaled diagonal inverse checks and all-output trtrs verification.
- Reason: inverse scaled C simulation failed; exclude from recommended cases pending diagnosis.
- No kernel changes; simulation-only. Validation results pending.

## 2026-09-11 — Exclude invalid inverse family
- Baseline 4/2 and scaled 256/128 both fail diagonal A=2I inverse identity check with residual 0.5.
- Added narrowly scoped cancellation helper for two in-flight inverse HLS trials; original algorithms and completed reports unchanged.
- Reason: avoid recommending or continuing known numerically incorrect inputs. Cancellation is not a resource-capacity result.
- Validation: explicit failed C-sim evidence and identical algorithm-header hashes required before cancellation; Vivado forbidden.

## 2026-09-11 — Final screening and synchronized evidence
- Completed three HLS batches and two C-simulation validation batches; added aggregate reports, qualified/recommended manifests, per-batch summaries and final HANDODD.
- Results: 36 attempted configurations, 32 RTL outputs, 8 resource/known-validity qualified configurations, 4 numerically checked recommendations. Other outcomes: 1 compiler failure, 1 inconclusive timeout, 2 known-invalid inverse cancellations.
- Validation: all completed RTL top modules and support-file hashes checked; 112/86/82 input hashes match; XML resources and device capacities cross-checked; selected LU/QR residual samples and all trtrs solution entries pass. Baseline and scaled inverse diagnostics fail and are excluded.
- Impact: parameter-scaled variants only; original library untouched. No physical timing or latency-equivalence claim.
- Limitations: HLS estimates, no Vivado synthesis/place/route, no C/RTL co-simulation, sampled LU/QR checks. SVD32 parameter invalidity retained explicitly. All raw artifacts remain on server; compact text/JSON evidence readable locally.
