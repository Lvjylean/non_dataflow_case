# Directed local-unit candidates

This optional resource-partition mode retains KaHyPar, logical-core preferences,
the existing merge-affinity threshold, protected storage/compute chains and
the exact `cut_weight*C + logical_core_weight*L` objective. It adds a structural
search neighborhood; it does not replace the solver or add a path/position term
to partition. Historical entry points and results remain unchanged.

## Discovery

1. Build the original register-bounded dependency graph. Ordinary supported
   LUT/CARRY/MUX cells use conservative cell-level arcs; RAM/DSP reuse the
   graph/DCP-bound native `macro_timing_v2` metadata. Never inject routed paths.
2. Every supported capture boundary and combinational join/fork is a root.
   Walk backward, admitting an interior node only after all its successors are
   inside the cone. This includes data and selector/control branches with the
   same rule, including reconvergence. Registers stop traversal.
3. A driver with an outside consumer stays at the boundary. All original net
   branches are checked against the supported graph: top ports and opaque or
   omitted arcs must not create false exclusivity. Broadcasts can have their own
   local candidates but do not merge all their consumers.
4. Project virtual timing nodes back to complete original physical atoms.
   Stateful/partially covered atoms stay at the boundary. A protected unit may
   move only in its entirety; discovery never expands one of its pins into a
   forced merge with unrelated consumers.
5. Store potentially overlapping **soft candidates**, together with anchor
   atoms. Candidates are not final modules and are not new hard units. No
   instance names, hierarchy whitelist, RAM-only root filter or fanout cutoff
   participates in discovery. No primitive/net/pipeline is changed.

The root work bound is 512 expanded nodes. Roots exceeding it are counted as
bounded and omitted, not labelled complete. This limits discovery work, not the
final module size. Roots at internal joins/forks still provide smaller candidates.
Current implementation scans roots and bounded reverse neighborhoods, rather
than enumerating paths; it is not claimed to be strictly linear in netlist size.

## Search and admission

After KaHyPar and the ordinary merge/refinement stages, retain the original
candidates and add a directed-unit variant of both the pre-refinement and
post-refinement assignments. The same discovered objects are reused.

Move all candidate atoms together, including atoms from several source modules.
Try anchor/current/incident-neighbor modules as destinations. Check the complete
resource vector, protected-unit integrity and the **unchanged experiment affinity
threshold**. Compute exact deltas on original hyperedges and logical-core edges:

`delta_J = cut_weight*delta_C + logical_core_weight*delta_L`.

Accept only strictly negative delta_J. No cone penalty, distance estimate, SLR
assignment or module-count preference is added. Original communication budgets
and final candidate ranking still apply; a locally improved but inadmissible
candidate cannot become the selected result. A full final rescore verifies
incremental deltas, complete membership and resource/protection invariants.

The first version does not move individual sequential cells as cone interiors,
hard-contract all discovered cones, or create new modules by splitting a group.
Existing KaHyPar candidates provide module alternatives; this stage improves
their boundaries. It need not eliminate every bad branch under the existing
C+L objective. Floorplan still independently scores accumulated SLR crossings.

## Entry points

Use the existing NumPy-enabled runtime for the parent process. KaHyPar generation
can continue to use its separate runtime; directed discovery runs during the
parent/evaluation stage, so NumPy is not imposed on the native solver runtime.

```sh
python3 structure_pipeline.py partition /absolute/new_run \
  --from-run /absolute/existing_resource_partition_run \
  --kahypar-python /absolute/kahypar_python \
  --kahypar-path /absolute/kahypar_binding \
  --directed-units --macro-timing /absolute/original_macro_timing_cache
```

The directed mode inherits the reference run's partition, structure and resource
configuration. It does not substitute public 70%/0.02 defaults for an experiment
using 60%/0.03. Discovery is graph/DCP/protection/hash bound and stored separately.
For an existing prepared fresh run, `evaluate --directed-units --macro-timing ...`
also enables this mode; its existing partition parameters are retained.

For a smaller validation on the previously selected partition, without rerunning
KaHyPar or floorplan:

```sh
python3 directed_unit_pipeline.py \
  --from-run /absolute/existing_resource_partition_run \
  --macro-timing /absolute/original_macro_timing_cache \
  --output /absolute/new_validation_directory
```

The output contains discovered candidates, coverage/work-limit counts, exact
before/after costs, move rejections, resources, connections and membership.
It does not replace the reference or produce implementation_input/pblocks.

## Coverage limits

The discovery rule is type-independent after graph construction. The current
graph adapter is not full STA: SRL/LUTRAM/latches and unlisted primitives are
opaque, LUT/CARRY/MUX are conservatively cell-based, and clock domains,
false/multicycle paths and sensitization remain unresolved. These gaps are
reported explicitly. Native macro metadata is mandatory when RAM/DSP are present;
absence or a mismatched graph/DCP binding fails rather than silently falling back.

Validation includes renaming and net-order invariance, data/control equivalence,
broadcast/reconvergence, register boundaries, native macro configurations,
outside/opaque consumers, work bounds, atomicity, protection, exact resource and
affinity gates, exhaustive small-graph objective deltas, and production selection.
No congestion, timing or frequency improvement is implied by these checks.


## Complete cached pass

`directed_cached_refine.py --from-run RUN --output NEW_RUN` reuses the selected
partition and its hash-bound `directed_units` discovery cache. An explicit
`--candidate-cache` may select a compatible cache. Graph, original DCP binding,
protection bundle, macro payload, candidate payload and unique IDs are checked.
No KaHyPar, rediscovery, floorplan or backend stage runs. Input files remain immutable.

The entry calls `refine(..., complete_pass=True)`: time and evaluation budgets do not truncate the pass. The actual acceptance
limit defaults to 64 moves; after reaching it, continue read-only evaluation and
record deferred improving proposals. Their gains are not additive. All cached candidates and each candidate's
current target neighborhood are evaluated once. The finite evaluation bound is
`number_of_candidates * input_module_count`; at most one move per candidate is
accepted. This is not all possible module assignments, repeated convergence or
a global optimality certificate. Existing limited-mode defaults remain unchanged.

The result records visited versus fully completed candidates, ordered/completed
ID hashes, effective bounds, progress and exact before/after C+L. The original
resource, protected-unit, affinity and final communication-budget checks apply.
A feasible unchanged current partition is retained as fallback.
