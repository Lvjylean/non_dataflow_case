# Frozen balanced plans: serial physical evaluation

The 2026-09-19 request authorizes sequential P&R of `slr_emphasis` (11 S modules)
followed by `selected` (12 B modules). Both independently start from the same
hash-bound post-opt DCP. No partition, ILP, RTL hierarchy or HLS changes occur.

`prepare.py` freezes and validates complete leaf ownership, resources, connectivity
eligibility, rectangular clock-region sets, and the source DCP SHA256.
`adapter.tcl` applies exact primitive members to soft Pblocks and checks their
native binding and resource-site geometry. There is no extra DSP child rectangle:
the supplied final modules already include the agreed granularity.

`serial.py` runs one implementation and independent DCP readback at a time.
Each has seed placement, spatial fanout96 identity trees, placement without PSIP
or BUFG optimization, phys_opt, fresh native protected-IP replication, up to seven
live-net cleanup passes (native target80 for margin), route, reports and readback.
The existing `fanout96/core.tcl` and `hybrid.tcl` are reused unchanged. Root
protection and exact sink-set proofs apply; no pipeline registers are inserted.
True clocks/constants are separately accounted for. Non-clock BUFG controls are
eligible regardless of the old export's infrastructure label.

Timing/fanout/soft-spill acceptance is separate from successful implementation.
An unmet acceptance gate does not stop the second case. A Tcl/process error does
stop the runner for diagnosis, preserving all evidence and checkpoints. The old
user acceptance of fanout does not certify these new outputs. The very expensive
all-net physical certificate is not a prerequisite; report its non-execution.
Manual tree proofs are local connectivity/identity checks, not sequential formal
equivalence. All large artifacts remain on eda070; preserve unrelated processes.

## Optional quick fanout implementation

The directed eleven-module experiment uses `seed_fast.tcl`, followed by
`run_fast.py RUN --implementation-script implement_quick.tcl`. This option
preserves the frozen seed and original region binding. The default runner still
selects `implement_fast.tcl`; previous immutable experiment snapshots are unchanged.
Deployment must include `connection_floorplan/audit.tcl` in addition to the
`balanced_implementation` and `fanout96` folders. The runner preflights these
readback dependencies before starting physical implementation. A completed DCP
can be independently reopened with `resume_readback_fast.py` if the documented
first-attempt dependency omission is encountered; this does not repeat P&R.

The quick entry point sources `fanout96/quick.tcl` after `fast.tcl`. It creates
at most 128 LUTs/nets per native command batch; disconnect/connect and complete
branch, root, original-sink-set and FF checks remain the same. This is a
combinational identity tree and does not add pipeline stages.

After a native target80 attempt, an unchanged complete residual driver/ref/sink
signature stops further retries. Enumeration order is ignored; equal counts
with different sinks or a new driver do not count as unchanged. A remaining
fanout violation is reported separately, and route proceeds. The decision is
recorded in `refinement_stop.tsv` and the final live scan remains mandatory.

`prepared.dcp` and `post_place.dcp` are omitted to reduce transient writes. Initial
constrained/seed DCPs, post-place timing/utilization, final routed DCP and independent
reopen evidence are retained. Recovery from an interrupted manual rewrite uses
the immutable seed, not a partial edited design.

Run `tclsh fanout96/test_quick.tcl` and the native `smoke_fast.tcl` with its optional
third argument `quick.tcl` before using this overlay. The native smoke includes
hierarchical BRAM/control rewrites and checkpoint reopen. Creation uses the
multi-name arguments documented in AMD UG835 2023.2 for
[create_cell](https://docs.amd.com/r/2023.2-English/ug835-vivado-tcl-commands/create_cell)
and [create_net](https://docs.amd.com/r/2023.2-English/ug835-vivado-tcl-commands/create_net).

Measured fanout time is the `fanout_begin` to `fanout_end` interval, including
replacement placement. It excludes the seed, final routing and reopen, and is
not a net overhead measured against a no-fanout control run. Forty minutes is
a measured target, not a guaranteed runtime. Reports detect the input objective
schema so the all-directed branch model is not described as the older sampled
timing-path objective.
