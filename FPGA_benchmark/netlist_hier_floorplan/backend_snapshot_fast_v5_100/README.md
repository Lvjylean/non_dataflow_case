# Maximum snapshot backend acceleration v2 (2026-10-06)

This isolated version derives from `backend_snapshot_fast100`. Current running
GETRF implementations retain their frozen original sources; this version never
hot-updates an active Vivado session.

* Physical cleanup resolves bounded native net collections once per streamed
  32,768-object batch, replacing repeated 512-object unroute calls. The complete
  affected-net union, fixed-route preflight, clock preservation and the separate
  physical supply cleanup remain mandatory. `PLG_CLEANUP_BATCH_SIZE` selects
  1..1,048,576 objects; larger values require memory/runtime qualification.
* Candidate input readback reuses a bounded view of this immutable live capture,
  generated from the already loaded complete graph. It preserves native pin
  traversal order, proves full load counts and clock classifications, and falls
  back to native reads for missing, ambiguous, unsupported or stale evidence.
  Actual configuration and setup/hold/timing-contract checks remain guarded.
  `BL_INPUT_REUSE_MODE=reference` restores original candidate readback.
* Verification resolves objects and properties in typed, plan-driven batches.
  Native collection provenance keeps same-name object classes isolated. Every
  check still executes in a fresh stage; no accepted result is cached. Capacity
  or metadata failure returns to native reads. `set ::vs::reuse 0` is the native
  reference selector for equivalence probes.

All physical decisions, complete D/CE/connection/protection/legality checks,
fanout<100, three normal placements, one complete route and independent reopen
are preserved. Detailed counters separate native calls, cache fallbacks, data
collection, unroute, reporting and stage elapsed time. Source-bound local and
native evidence must be regenerated for this version before production admission.
The historical seven-hour active time excludes admission waits. Whole-design
speedup cannot be inferred from call-count reduction or small fixture timings.

The sections below describe inherited capabilities and historical contexts.

# Shared snapshot backend acceleration (2026-10-06)

Entry: `run_case.py`. This isolated copy preserves the original production flow
and running experiments. Physical candidate rules, D/CE guards, fanout<100,
three normal placements, one full routing and independent reopen are unchanged.

* `locality_inventory.tcl` batches hierarchical PARENT-group mapping and pin
  metadata. It keeps an authoritative per-net leaf-pin incidence query; Vivado
  2023.2 pins do not expose a validated NET_NAME mapping. Missing/ambiguous
  parent metadata falls back to complete reference queries. Set
  `BL_INVENTORY_PROFILE=reference` for the original capture path.
* The live inventory's cell ref/CR/SLR metadata is shared only during a guarded
  immutable discovery context. Checkpoint-cache hits do not reuse old live data.
* Python preparation streams large tables. Cone candidates share one immutable
  Graph; input structural groups and multi-endpoint cone delay analysis are
  reused without caching geometric, D/CE, resource or fanout acceptance.
* `verification_snapshot.tcl` shares actual native queries and properties within
  each read-only validation stage. ECO/place/route/restoration run outside it;
  mutation invalidates the context. No PASS flags or actual data survive into
  another physical stage or the independent reopened process.
  Queries retain original Vivado collections, and native object classes keep
  same-name cells, nets and Pblocks distinct. Missing class metadata or cache
  capacity falls back to live reads. Stage caches have entry/object budgets;
  classification calls and budget bypasses are reported explicitly.
* Static checkpoint retry reuse requires the new complete-source-bound native
  v2 equivalence proof. Restore retains complete hashes, independent copied-file
  verification and atomic installation while eliminating one full source read.

Local and native validation evidence belongs outside this source directory.
The native cache harness is `run_static_discovery_cache_probe.py`; it performs
three independent discovery/STA replays, no ECO/place/route. Production reuse
stays disabled until its current-source proof passes. Pure-Python benchmarks are
local work measurements, not estimates of a complete Vivado compilation speedup.

# Runtime acceleration with unchanged physical decisions

This isolated copy derives from the 138-file validated
`backend_broadcast_locality100` snapshot. It preserves the original module
floorplan, candidate algorithms, positive placed-WNS policy when selected,
fanout limits, full setup/hold guards, legality checks and independent reopen.
The withdrawn local LUT placement experiment is not part of this flow.

Runtime changes reuse parent protection properties only within one immutable
inventory capture and Pblock memberships only within one verification call.
The optional, separately validated retry cache reuses complete static inventory
and preparation output only after the controller reopens the same verified base
checkpoint. Candidate exclusion, final planning, timing and all post-edit checks
run again. Cache mismatch or incomplete evidence falls back to fresh scanning.
No cache is reused across ECO or physical stages.

The GETRF 6.7 ns experiment starts from clean post-opt and executes the complete
pipeline. The historical 6.5 ns route-only and second-placement recovery runs
have different timing scopes; their totals are not a full-flow speed baseline.
Inventory stage timings and cache hits/misses provide phase-level evidence.

# Complete endpoint timing extraction acceleration

This independent copy preserves `backend_joint_input100` and its results. Default
`--timing-extraction pin` updates the current timer once, resolves exact endpoint
names, then reads SETUP_SLACK/HOLD_SLACK in 2048-object batches. Every guarded
endpoint remains in the output; empty/nonfinite properties invoke the original
path search. Missing objects or inconsistent property/path coverage fail closed. Known top-level
PORT endpoints retain the original global-summary coverage and are explicitly
listed in the coverage report; they are not misclassified as missing cell pins.
No slack values are cached across design mutations or physical stages. Large
endpoint dictionaries are materialized once into scalar rows and array-indexed
for serialization; this avoids repeated native-backed dictionary conversion.

The candidate planner still obtains path REQUIREMENT; only property extraction
from returned paths is batched. `joint_gate.py` is unchanged, including per-endpoint
floors, global setup/hold protection, owner attribution and bounded retry.
`--timing-extraction reference` selects the archived original query algorithm.
Full exact connections, fanout, changed-D legalization, placement legality,
regions, one complete route and independent reopen remain mandatory.

Production admission additionally requires `native_fast_timing_equivalence_pass`.
Validation uses complete archived GETRF before/placed endpoint tables plus native
MUX/FF modification, placement, route and reopened checks. The 6.5 ns experiment
starts from the same clean post-opt DCP and original 22-module floorplan. Phase-level
and individual extraction calls are recorded separately; historical 6.7 ns times
include recovery and do not isolate cycle or server-load effects.

# Joint FF/input-cone backend with physical and timing guards

This isolated copy extends `backend_legalized100`; earlier sources and runs are immutable.
The supported production entry is `run_case.py`. Legacy `joint_eco` files remain
reference adapters, not the planner used by this entry.

## Pipeline

Clean post-opt and the same module floorplan -> seed placement -> base fanout
reduction and second placement -> bounded FF/input-cone planning -> exact ECO
and changed-D physical release -> third normal placement -> input/output STA
and physical legality gates -> one full routing -> independent reopen.
One timing-rejection retry is permitted from `base/pre_route.dcp`. The failed
attempt is preserved as `generic/rejected_attempt0`; there is no routed result
for a rejected candidate. A second rejection stops. Shared-Slice repair remains
bounded independently by the existing physical gate. Normal compilation still
uses three placements; a rejection or physical repair can add placement work.

`--resume-base-root` and `--resume-base-sha256` can recover a stopped discovery
failure into a new output directory. Admission requires unchanged clean input,
period, floorplan and seed/base code, plus the completed base checkpoint hash.
Earlier seed/base artifacts are referenced read-only; failed output is preserved.
The reported compile time includes the prior failed attempt, not just recovery.
SLL reservation runs are not supported by this recovery boundary.

## Candidate planning

`code/regional/joint_input.tcl` captures cached connectivity, all D-cone input
branches, actual CR/SLR locations, per-endpoint setup/hold, clock requirements
and native SLR utilization. Traversal stops at sequential/memory boundaries;
unknown ports, protected or unsupported structures and timing exceptions are
rejected with reasons. No register names or fixed clock period identify targets.

`joint_input.py` compares FF-only, source-local upstream groups plus a target-local
terminal group, and target-local cones. LUT1..6 and complete MUXF7/8/9 data macros
are copied without changing logic depth. All select inputs are retained.
Placement centers and moved-load counts use only original placed receiving pins.
Planned replica inputs have no physical location yet and are budgeted separately;
they are never queried as existing cells or subtracted from original fanout.
Low-fanout internal cells can participate. Identical cone replicas are shared
only when their source, target SLR and complete mapped inputs match.

The CR distance model predicts incremental D delay against measured original
setup slack across every data/select branch. CE/R/S budgets are checked separately.
The model coefficients are explicit heuristics, not calibrated routed delay
bounds. Predictions cannot guarantee routed timing. Default setup margin is0.2ns,
configured by `--joint-margin`; per-endpoint copied-logic budget512 and global8192
are configured by `--joint-per-endpoint` and `--joint-max-added`.
Global shared upstream fanout and native SLR LUT/FF/MUX capacities are checked.
The CLB capacity adapter currently targets UltraScale+; unsupported architectures
must supply a validated adapter. Functional primitives and all nets are preserved.

This release jointly admits FDRE/FDSE roots and their input cones. Standalone
LUT broadcast duplication is explicitly deferred because its independent timing
model is not implemented. Basic fanout-tree processing remains active; deferred
roots remain available to regional processing. This limitation is recorded per
candidate, not silently counted as optimized.

## Location and functional checks

New copies enter hard whole-SLR parents with rectangular soft child windows
made of clock regions, clipped to that SLR. LOC/BEL are not locked. Original
module Pblocks and members remain unchanged. Exact clone functions, every
original and added connection, all input semantics, FF/LUT/MUX counts, location
contracts and ordinary fanout<100 are verified. New memories/pipeline stages
are never created. Original sinks may move under their existing constraints.

The physical edit contract uses `physical_eco.tcl`: clean incident stale routes,
unplace modified-D FFs, repair a bounded set of shared Slice occupants if needed,
and require zero illegal/unplaced/stale-routed sites before routing. Final and
independent-reopened checks require complete routing with zero routing errors.

## Timing admission and recovery

`joint_gate.py` checks original affected endpoints, new FF D/CE/R/S pins, output
endpoints, shared-input side effects and a global critical guard set. Positive
baseline paths cannot become negative; existing negative paths cannot worsen.
Global placed WNS/TNS cannot worsen and hold checks remain binding. D and Q
paths are independent timing intervals and cannot offset each other's failure.

The gate runs before routing and persists `joint_placed/acceptance.json` and
`PASS`. Rejected groups include shared cone/input dependencies; unassignable
side effects conservatively reject the whole batch. The controller reloads the
unedited baseline, rebuilds a smaller plan and permits one retry. It never
reuses the failed placement or weakens timing/structural checks. Final routed
numeric misses are annotations, while physical or structural failures stop.

## Validation and reports

`test_joint_input.py` covers backtracking, all-input protection, complete MUX
groups, shared fanout, control margins, timing exceptions, resource budgets,
atomic rejection and literal Tcl serialization. `test_joint_retry.py` executes
the real controller against rejected-process fixtures on Linux and checks that
only one retry is made and no routing occurs. Existing regression suites remain.
`native_joint_input.tcl` exercises the real planner and an entire LUT/MUX/FF
copy, placement, STA gate, route and independent reopen. Production requires
current source hashes and native evidence. Inherited changed-D packing regression
evidence remains required. Seven-section reports include candidate decisions,
input estimates, placed guard results, retries, all final checks and timings.

Pblock hierarchy and soft-child semantics follow AMD UG905 Pblock Constraints:
https://docs.amd.com/r/2023.1-English/ug905-vivado-hierarchical-design/Pblock-Constraints
and UG912 IS_SOFT (2023.2):
https://docs.amd.com/r/2023.2-English/ug912-vivado-properties/IS_SOFT

## Existing SLL reservation option

`plan_sll.py` reads exactly one initial SLL Assignment demand table from the
completed control run. It tests integer demand/capacity >= 80%, not the rounded
percentage and not whole-boundary utilization. The device-specific implementation
currently supports only U250, with 16 columns of 1440 SLLs per boundary.

`sll_balance.tcl` maps native crossing nodes to the corresponding Laguna TX/RX
BELs through the device graph. Each selected bundle reserves 480 distinct SLLs
using fixed, connected dummy FDRE pairs, distributed throughout its rows. These
cells share the existing buffered clock but do not connect to functional data.
The pair endpoints are connected before BEL and LOC assignment. The occupied
resources are present during all placement and intervening physical optimization
stages. They are removed after final placement, before clock-route update and
full routing. The removal audits the functional pins on shared nets and the
functional primitive count. Placeholders are excluded only from the functional
FF count and are required to be absent from final placement and reopened audits.

The native validation routes a small test containing the placeholders to prove
that each pair really occupies its requested SLL node. This test-only route is
not added to the full GETRF compilation. A second native integration test runs
the entire normal flow and removes the placeholders before its only full route.

`--sll-plan` requires native reservation evidence for production. A finite
experiment controller waits for a valid completed control run, creates a plan,
and starts one reservation run. Numeric timing or fanout misses are annotations.
Unknown structural errors stop with evidence; no constraint is relaxed.

Method reference: https://jasonlau.io/research-papers/10.1109-ICCAD66269.2025.11240757.pdf
Sections VI-C and VII-B describe temporary Laguna-register reservations. The
80% threshold and one-third blocking ratio here are user-selected, not a copy
of the paper's multi-tier policy. Source changes and validation costs are kept
separate from measured compilation time.


## Static discovery cache for the bounded retry

This runtime copy may reuse the complete `cells.tsv`, `edges.tsv`,
`diagnostics.tsv`, `metadata.tsv`, `proposals.json` and `requests.tcl` from the
first generic attempt when the timing guard requests its one permitted retry.
The controller reopens the same base checkpoint; the base already contains its
fanout edits, while the cached evidence precedes all generic ECO edits. Reuse
requires matching checkpoint bytes, complete frozen source inventory, Vivado
version, part, clocks and prepare parameters, plus per-file hashes. Missing or
incompatible evidence falls back to fresh discovery. Native template checks,
STA, `finish` admission with the new exclusions, live edit-boundary checks and
all subsequent acceptance checks still run. Failed plans and placement are
never cache inputs.

Production reuse is disabled until `native_static_discovery_cache_probe.tcl`
passes separate `live`, `fresh` and `cached` runs against one tiny checkpoint.
The verifier checks complete static equivalence and matching retry admission
with a nonempty exclusion. Only the metadata capture time and source paths may
differ between independent captures; all six files remain byte-exact on an
actual cache hit. A reused `metadata.tsv` retains its original `elapsed_ms` as
source evidence: it is **not** new retry runtime. The cache receipt records
lookup/copy time, and controller stage wall times remain the compilation metric.
