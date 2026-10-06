# RAM/DSP coverage update (2026-09-27)

The current default is `cumulative_paths.topology_model = macro_timing_v2`.
The FF-only scope described below is retained as historical `ff_cell_v1`.
Missing `topology_model` in an old explicit configuration selects that historical
model; a new configuration cannot reuse its cache without rebuilding.

The exponential curve and weights are unchanged. Active native RAM/DSP timing
arcs add capture and launch boundaries. DSP48 expansion is traversed through
its DSP_* subprimitives, preserving combinational bypasses and stopping at
internal registers. Disabled native arcs are excluded. All capture pins of an
original cell contribute one maximum, retaining the original per-cell weighting.
Macro-internal zero-distance arcs are compressed with exact input/output/state
frontiers, and identical output dependency sets share a factor node.

This remains a structural proxy: ordinary LUT/CARRY/MUX nodes are conservative
cell-level arcs; SRL/LUTRAM/latches and other unlisted macros remain opaque.
Clock domains, false/multicycle paths and sensitization are not STA-filtered.
Soft extension, placer spill and backend replicas do not change core scoring.

One-time, read-only cache preparation on the Vivado server:

```sh
vivado -mode batch -source macro_timing_extract.tcl -tclargs POST_OPT_DCP RAW_CELLS_TSV NEW_NATIVE_DIR
python macro_timing.py --graph ORIGINAL_GRAPH_PKL --native NEW_NATIVE_DIR --raw-nets RAW_NETS_TSV --dcp POST_OPT_DCP --output NEW_MACRO_CACHE
```

Then pass `--graph ORIGINAL_GRAPH_PKL --macro-timing NEW_MACRO_CACHE` to
`floorplan_cached.py`. For `structure_floorplan.prepare`, supply the optional
`macro_timing` argument, or place the cache at `ROOT/macro_timing`. The native
cache is bound to the original DCP and graph, independent of partition membership;
it can be reused across memberships. The resulting path topology additionally
binds the frozen leaf membership. Subsequent searches reuse the topology and do
not reopen Vivado. Missing macro metadata fails before creating a cached run or
starting the floorplan initialization; it never silently drops RAM/DSP paths.

The historical square `control_path_cost.PathModel` is unchanged. Only the main
exponential path model receives this upgrade, including incremental scoring and
the independent final verifier.

---

# Register-bounded exponential SLR cost in the main floorplanner

The current `directed_config.json` enables `cumulative_paths`. This augments the
main fixed-membership floorplan objective. It does not change partition C+L,
module members, the existing hypernet model, directed distance/branch-square
weights, resource limits, or the core-only accounting of soft extensions.
Historical configurations without this section retain their original scores.

For every supported capture register t:

```
Nmax(t) = max over structural launch-to-capture paths p of
          sum_{(u,v) in p} abs(SLR(module(u)) - SLR(module(v)))
P = 128 * sum_t (2 ^ max(Nmax(t)-1, 0) - 1)
J = existing full floorplan J + P
```

The added per-endpoint penalties for N=0,1,2,3,4,5 are respectively
0,0,128,384,896,1920. Uniform endpoint weights require no routed report or
criticality extraction. This exponential curve differs from the preceding
optional control repair's square curve; base 2 is not automatically steeper
than a square at every small crossing count. The new curve is not normalized
and has not been calibrated against a new placement/route result.

## Algorithm and search integration

`cumulative_paths.topology` uses original cell connectivity and physical-atom
membership to build a register-bounded DAG once. Clock/constant exclusions are
inherited from the original extraction. Registers act as separate launch and
capture boundaries; a capture value never becomes the next cycle's launch value.
Maximum-count propagation evaluates all supported structural paths without
enumerating them. Parallel/reconvergent branches take a maximum, not their sum.

`CumulativePaths` caches scores by the modules' SLR assignments. Moving within
the same SLR reuses the path score. When assignments change, incoming/outgoing
edges incident to changed modules seed a topologically ordered work queue.
Changed values propagate downstream; unchanged values stop propagation. Both
increases and decreases are recomputed from all predecessors, including when
a former worst predecessor stops being worst. Register boundaries stop updates.
Rejected trial layouts and assignment-cache hits do not alter correctness of
the next update. If a dirty cone exceeds 20,000 visited nodes, the scorer falls
back to a full vectorized pass; it does not truncate the path or its penalty.
Worst-case work may still approach the full graph. The assignment cache holds
512 entries. Exponential overflow raises an error rather than silently capping
or dropping the cost.

The term is evaluated inside `directed_search.Search.score`, so coordinate
refinement, swaps, annealing, die permutations and final candidate selection in
`fixed11_search.py`/`fixed11_explore.py` all use it. Resource-repair and packing
only propose starts; starts are rescored with full J. The optional MIP and
`structure_floorplan.seed_regions` remain surrogate initializers, not full-J
optimality certificates. No new search algorithm or outer P&R loop is added.

`fixed11_verify.py` independently recomputes the final term with scalar forward
relaxation and powers. The original hypernet/directed/resource audits remain.
Soft expansion retains core cost; it does not recalculate P using the envelope.
Optional intact-chain subdivision verifies that every child keeps its parent's
single SLR, making the parent's path term invariant under that step.

## Supported geometry and timing scope

The enabled first release uses **single-SLR core regions per physical module**.
This does not fix which SLR is chosen, prevent overlapping regions, force
equal-sized modules, or alter soft-envelope rules. Existing multi-SLR references
are recorded as unsupported and are not assigned a zero penalty. Search uses
single-SLR candidates; if a module has none, it fails explicitly. Multiple-SLR
modules need an internal location model before this path count can be extended;
the implementation does not substitute their center or independent random
SLRs and pretend the count is exact.

Coverage is FDRE/FDSE -> LUT/CARRY8/MUXF7/MUXF8 -> FDRE/FDSE. Opaque DSP/RAM,
LUTRAM/SRL, latches and other primitives are reported in `path_coverage.json`
and are not given guessed internal arcs. Clock-domain separation, false paths,
multicycle constraints, LUT functional sensitization and precise macro register
modes are absent from this structural cache. Therefore the count is a
conservative structural proxy under a one-cycle assumption, not full STA or a
promise about routed SLR crossings, delay, WNS or soft-Pblock spill.

## Cache/entry points

Fresh `structure_pipeline.py` runs carry the current path settings into their
frozen source configuration. `structure_floorplan.prepare` builds and binds
`path_topology.pkl`, `path_binding.json`, and `path_coverage.json` from the graph
already in memory. Path construction happens after partition membership freezes.

For a new fixed-membership rerun, `floorplan_cached.py` reuses a valid path cache
or builds it from the original graph and exact frozen leaf membership:

```sh
python floorplan_cached.py NEW_RUN --from-run PREVIOUS_FLOORPLAN \
    --graph ORIGINAL_GRAPH_PICKLE
```

This command runs static floorplan search; it is not needed merely to validate
the code. `--graph` can be omitted if a valid path cache exists or the previous
run's parent has the matching original `graph.pkl`. Pair-only caches cannot
recover register boundaries. Cache loading fails on missing graph provenance,
changed membership, changed payload hash, or different module IDs. Input and
source manifests include the new cache files. No DCP is opened to build them.

The older `control_path_refine.py` remains a separately documented, report-driven
square-penalty experiment. Its old configuration and delivered GETRF input are
not retroactively relabeled as exponential results. The new default belongs to
the main floorplan scorer and works without that control-repair stage.

Run tests with `python -m unittest test_cumulative_paths test_cumulative_integration`.
They compare all 256 four-node SLR assignments with explicit path enumeration,
random accepted/rejected moves against scalar recomputation, main scorer/local
search/final verifier integration, legacy replay, and graph/member cache binding.
