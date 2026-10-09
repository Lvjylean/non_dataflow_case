# Fast v5 update — 2026-10-09

This update adds `backend_snapshot_fast_v5_100/run_case.py` as the isolated accelerated backend. The existing `backend_broadcast_scope_repair100` and partition/floorplan sources are preserved.

## Fast implementation

- Batch ordinary name lists with standard Tcl operations, avoiding expensive Vivado-overloaded list slicing; retain canonical native objects to reduce name-to-object round trips.
- Reuse bounded live candidate input snapshots and array-backed cell/net indexes; normalize receivers and group canonical broadcast roots once per immutable context.
- Batch physical cleanup and typed verification reads, with stage-local invalidation and native fallbacks. Never cache PASS results across ECO, placement, routing, or independent reopen.
- Increase candidate serialization allowance to 128 MiB while preserving structural budgets and complete D/CE checks.
- Add production `-notrace` launch handling and candidate/substage timing diagnostics; include native performance/equivalence probes.

## Scope and validation

The published snapshot contains 180 source/test/documentation files: 25 modified and 27 added relative to the 153-file original backend (no deletions). It preserves fanout rules, physical candidate decisions, timing gates, three normal placements, one full routing, and independent reopening. Numerical timing/fanout targets can still fail and must be reported honestly.

The local Fast v5 work record reports ten native validation stages passing in 263.013 seconds and subsequent full GETRF runs. These are historical validation results, not tests rerun by this publication. Runtime depends on period, recovery, workload, and concurrency; no universal speedup is claimed. Source-bound certificates must match the selected source and environment before cache admission.

Partition/floorplan: all 139 published connection_partition files remain byte-identical. See RELEASE_10_6.md for algorithm features. Large experiment outputs, DCPs, and logs are excluded.
