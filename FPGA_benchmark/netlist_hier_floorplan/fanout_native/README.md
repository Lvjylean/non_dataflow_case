# Native-first high-fanout handling, revision 3

The `fanout_new` branch archives the current revision-3 implementation at the
user's request on 2026-09-20. It includes the runtime performance, macro-protection
and native-identity audit fixes used in subsequent implementation experiments.
Those experiments completed placement, routing and independent checkpoint
readback; setup timing did not close. Netlists, checkpoints and experiment
reports remain outside this source publication.

This is an archival baseline, not a claim that revision 3 improves timing.
The placed residual planner can mix SLRs when packing site groups, while its
majority-SLR placement heuristic can introduce new cross-SLR detours. The
pre-placement upper tree also does not preserve owner labels at every level.
These known spatial-quality issues are intentionally retained in this snapshot;
no proposed algorithmic fix is included. Floorplan research currently returns
to the older directed flow, archived separately as `highfanout1`.
The old published implementation remains in
[highfanout1](https://github.com/Lvjylean/non_dataflow_case/tree/highfanout1).
No historical code, checkpoints or reports are overwritten by this revision.

## Execution

```text
Frozen post-opt DCP + unchanged module soft Pblocks
  -> complete live-net classification, including mixed-use clock-pin nets
  -> pre-placement identity trees for memory / special ordinary outputs
  -> protect identity cells, leave signal nets editable
  -> check native driver input/output/ancestor protection
  -> set FORCE_MAX_FANOUT on eligible FF/LUT and one level of upstream drivers
  -> place_design once, with physical synthesis enabled
  -> inspect placement residuals
  -> zero or one targeted phys_opt_design, without iterative target halving
  -> one bounded residual ECO batch for all supported ordinary driver classes
  -> locally place only new helpers; verify LOC/BEL and connectivity
  -> final independent logical audit, route, checkpoint, read-only reopen
```

There is no seed placement, second global placement, default phys_opt followed
by repeated native passes, new pipeline stage or RTL modification. Native FF
replication is allowed; every manual ECO separately checks its FF count invariant.

The final residual batch includes FF/LUT generations created by the optional
native pass. Its trees do not create additional loads on their upstream sources:
they replace selected existing loads with a bounded frontier of identity inputs.
All live nets are scanned again afterwards. This is not a promise that every
network can be modified or that every implementation will meet logical <100.

## Driver and branch handling

| Source / branch | Handling |
| --- | --- |
| Eligible FF/LUT ordinary output | Native first-placement request; at most one later native pass; bounded manual fallback if residual. |
| BRAM/URAM output | Combinational LUT1 tree before placement; same residual handler if a later output exceeds the limit. |
| Non-clock BUFG-family / IBUF / input port | Identity dispatch both before and after placement, rather than recording an unused OTHER_IDENTITY list. |
| CARRY4/CARRY8 ordinary output loads | Identity dispatch; dedicated carry input branches remain directly connected. |
| Mixed ordinary and clock-pin loads | Included in logical acceptance; manual branch split retains clock-pin connections. Never pass the whole mixed net to unrestricted native replication. |
| Clock object / clock-pin-only net / constant | Separate explicit category. Numeric mixed exclusions in legacy rows are conservatively counted, not automatically exempted. |
| Protected cell, ancestor, net, ASYNC_REG, observed protected IP manual-edit family | Preserve and report. Native requests additionally check every input electrical segment for DONT_TOUCH. |
| Other primitive / multiple drivers | Explicit unsupported annotation; no speculative primitive duplication. |

BRAM, carry and control sources retain their original functions. Clock and
cascade sinks are never routed through the added LUT tree. A preserved sink is
included in the root fanout budget. Insufficient remaining root capacity is
reported as `RETAINED_ROOT_LOADS_EXHAUST_TARGET`, not hidden from acceptance.
For post-placement edits, all selected loads in one occupied site form an
indivisible group; sites containing a preserved/protected load remain unchanged.
An atomic group larger than the target is annotated rather than split illegally.

## Protection and connectivity

The identity primitive has `INIT=2'h2` and cell-level DONT_TOUCH. Revision 3
**does not add DONT_TOUCH to the original root or helper output nets**. Original
user/IP net and cell protections are never globally removed. Only our own helper
cell protection may be temporarily released to reconnect a helper input/output,
and is restored after the edit, including exceptions.

Immediate readback checks every branch, retained root load and reconstructed
original sink multiset. The generated identity manifest records all expected
helpers, so removing a helper cannot silently pass an audit that only enumerates
survivors. Final/reopened audits verify the manifest, identity functions,
cell-level protection, absence of newly locked helper output segments, and helper
placement. The runner hashes the identity manifest before/after independent reopen.
Manual helpers are matched by exact manifest names. Native LUT copies with verified
ORIG_CELL_NAME/FANOUT_OPT provenance and BUFG_OPT buffers are recorded separately
in identity_cells.tsv; a shared prefix alone never certifies a manual identity.
All original helpers must remain, and native identity copies retain identity and
cell-protection checks. Unknown prefixed objects are rejected.
Native duplication may legitimately add or rename downstream loads; the manual
before/after exact-coverage proof is not presented as sequential formal equivalence
of all subsequent Vivado transformations. No complete formal proof is claimed.

Discovery batches pin metadata and caches cell/ancestor protection rather than
querying every ordinary pin separately. Each tree plan is constructed once before
edits; there is no duplicate full planning pass for budget preflight. The previous
Vivado-native collection performance issue was diagnosed during revision 3;
this snapshot includes the resulting traversal and caching corrections.

## Local placement and bounded fallback

The residual ECO batch creates only LUT1 helpers. It selects unused SLICE sites
near the load group's clock-region centroid, favoring the majority load SLR.
There are no per-CR helper Pblocks or moves of existing cells. `place_cell` is
called without `-quiet`, and its result is accepted only after LOC/BEL readback.
Empty SLICE sites are used conservatively rather than repacking existing logic.
This is a legalization heuristic, not a new floorplan optimization or timing proof.

New helpers are placed **before** any original endpoint is disconnected. If
placement cannot complete within the attempt bound, those unconnected helpers
are removed, the original graph is untouched, and the driver is recorded as
`LOCAL_PLACEMENT_UNAVAILABLE`. Connectivity errors after rewiring stop the run
with retained evidence. No unplaced helper is allowed to proceed to routing.
Other deferred reasons include global/post-place helper budgets, original
protection, unsupported driver types and oversized shared-site groups.

## Configuration and entry point

```sh
python3 FPGA_benchmark/netlist_hier_floorplan/fanout_native/run.py INPUT NEW_OUTPUT
```

Only run the physical command when explicitly requested. `--prepare-only` is an
offline bundle preparation mode and does not execute Vivado. Both the adapted
manifest/membership/regions format and the existing unadapted implementation_input
format remain supported; the original post-opt DCP is hash-bound and preserved.

| Setting | Default | Meaning |
| --- | ---: | --- |
| `native_target` | 96 | Native physical SITE-pin target. |
| `memory_target` | 96 | Manual logical branch/root construction target. |
| `refinement_passes` | 1 | Only 0 or 1 is accepted; old values 2..8 are rejected before execution. |
| `upstream_levels` | 1 | Mark one level of eligible non-clock input drivers, including currently small nets. Set 0 to disable. |
| `post_place_lut_budget` | 4096 | Total helper limit for the final residual ECO batch; 0 disables edits with explicit annotations. |
| `local_site_attempts` | 64 | Maximum candidate sites attempted per new helper. |
| `memory_lut_budget` | 50000 | Global manual-helper budget. |
| `native_mode` | NONE | No new MAX_FANOUT_MODE; optional SLR/CLOCK_REGION/MACRO values retained. |
| `native_min_target` | 8 | Legacy validated compatibility field; no effect because target halving is removed. |

The logical audit always scans above 96 and treats **100 as a violation**. It is
independent of the configurable physical target. FORCE_MAX_FANOUT is not a strict
logical-pin certificate. Physical SITE-pin counts cover final over-threshold
candidates, not every net. Timing/fanout/soft-region acceptance remains an
annotation policy; a completed run is never relabeled failed solely for a
fanout target miss. Unsupported/protected networks are visible in final actions.

New execution dependencies include `scan.tcl` and `eco.tcl`. Historical collectors
that assumed only memory_patch edits, exactly three native passes, or locked root
nets must use revision-3 records instead: `residual_patch/`, `identity_manifest.tsv`,
`final_actions/`, and the new identity audit columns. The old per-experiment frozen
collectors are intentionally not modified.

## Offline verification

```sh
tclsh FPGA_benchmark/netlist_hier_floorplan/fanout_native/test_policy.tcl
tclsh FPGA_benchmark/netlist_hier_floorplan/fanout_native/test_eco.tcl
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
  -s FPGA_benchmark/netlist_hier_floorplan/fanout_native -p 'test_*.py' -v
```

Tests model real electrical connections, reserved clock/carry branches, input-net
protection, final-generation dispatch, shared-site atomicity, failed placement
rollback, LOC/BEL validation, helper manifests and immutable execution artifacts.
They do not invoke Vivado. Before relying on a future physical result, verify
cell-only helper protection and the local placement API against native Vivado.

## AMD references, Vivado 2023.2

- [FORCE_MAX_FANOUT](https://docs.amd.com/r/2023.2-English/ug912-vivado-properties/FORCE_MAX_FANOUT): FF/LUT output nets and physical SITE-pin fanout during placement.
- [place_cell](https://docs.amd.com/r/2023.2-English/ug835-vivado-tcl-commands/place_cell): placement of specific new cells; `-quiet` suppresses error return codes.
- [phys_opt_design](https://docs.amd.com/r/2023.2-English/ug835-vivado-tcl-commands/phys_opt_design): optional post-placement physical optimization.
