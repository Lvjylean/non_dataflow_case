# Partition and floorplan release — 2026-09-22

Branch: `codex/partition-floorplan-9_22`, based on
`codex/partition-three-step` (`54337f327bd9954d9cec47d364824607ccc919cf`).
This is a source/configuration release of the validated static workflow, with
the current fixed-eleven floorplan entry point. It does not run implementation.

## Version progression

| Version | Completed capability | Boundary of that version |
| --- | --- | --- |
| `originalpart` / `8bcc512` | Complete post-opt leaf/connectivity extraction, dedicated atoms, KaHyPar km1 candidates, capacity-safe greedy merges, resource and connection exports | Connectivity-first coarse modules; hierarchy is provenance; no logical-core preference or CR floorplan search |
| `codex/partition-three-step` / `54337f3` | Selective affinity merges; logical-core and atom/whole-core boundary refinement; resource-driven local splits/regrouping; actual CR-capacity and overlapping-region evaluation | Three-step experimental comparisons, including a static sibling-coupling preference; not the later unified balanced objective or directed fixed-eleven floorplan |
| `codex/partition-floorplan-9_22` | Balanced candidate admission/scoring and split/merge/refine search; all-atom hypernet span model; fixed-eleven directed source/sink distance and multi-SLR branch penalty; exact soft-Pblock expansion after optimization | Finite static heuristics; no global optimum, routed timing, SLL, congestion or functional-equivalence claim |

The balanced partition can produce several alternatives. The current eleven
modules were the selected S-prefix alternative used by subsequent experiments;
eleven is not a hard constraint of the balanced partition generator. The new
cache-only floorplan entry point deliberately freezes S00–S10.

## Separate partition and floorplan configurations

`balanced_config.json` remains the configuration used to generate the existing
module alternatives. Its physical SLR coefficient remains 4. Do not change that
value merely to reproduce the later fixed-membership floorplan.

Its composite objective is

`J_partition = D_all + 2*C_real_km1 + 2*L_soft_core + 0.0025*W_all*k`.

The soft core set uses 8–32768 cells and cohesion >=0.2; synthetic core-edge
strength is 0.1. Additional real km1 must fit the global 0.025*W_all budget and
each original parent's 0.10*incident-weight budget. Candidate selection retains
the original 1% score tolerance and fewer-module preference. See [balanced.md](balanced.md).

`directed_config.json` and `edge_padding.py` publish these floorplan defaults:

| Parameter | Value |
| --- | ---: |
| Per-CR aggregate non-URAM resource limit | 70% |
| URAM limit | 100% |
| SLR distance coefficient | 8 |
| Directed-distance coefficient | 1 |
| Multi-SLR branch-square coefficient | 32 |
| Soft-extension trigger | strictly greater than 50% |
| Core-region area window | 1.5 * minimum feasible CR area + 4 |

`J_floorplan = X_all + Y_all + 8*S_all + X_dir + Y_dir + 8*S_dir + 32*P_branch + C_fixed`.

`P_branch = sum(weight * E[max(0, abs(SLR_driver-SLR_sink)-1)^2])`.

The objective is not normalized. Directed terms retain modeled sink-pin
multiplicity, including internal-module branches; this is **not accumulated
same-cycle path cost**. Top ports without locations and excluded infrastructure
remain explicit limitations of the input cache. Positions are independent,
capacity-proportional estimates. Routed-density fitting is disabled; its shared
compatibility helper is not an enabled feature of this release.

The core is optimized first. A boundary CR with aggregate single-resource usage
above 50% can add a four-edge-adjacent, same-SLR CR that no module's **core** covers.
Every eligible module can share that extension. There is one expansion pass,
without diagonal or recursive filling. Soft-only CRs change exported geometry
and the diagram, never resource capacity, demand, or J. No URAM80 special rule,
forced S01 whole-SLR override, 40% trigger, or 60% density setting is active.

## Re-run the fixed-eleven floorplan from an existing cache

Requirements: Python 3, NumPy, Pillow and Tcl for adapter tests. This local
search does not require Gurobi, KaHyPar, Vivado or a server connection. Only use
trusted pickle caches prepared from the same checkpoint and membership.

The input run must contain:

```text
input/export/modules.json              # S00–S10 metadata and resources
input/export/static_regions.json      # previous unexpanded core reference
input/export/...                       # unchanged module export files
input/original_regions.json            # earlier reference layout
input/cr.tsv                           # matching device CR capacities
netmodel.pkl                           # all-atom hypernet model
directed.json                          # source/sink branch model and exclusions
binding.json                           # immutable input hashes and fixed cost
```

From the repository root:

```sh
python3 FPGA_benchmark/netlist_hier_floorplan/connection_partition/floorplan_cached.py \
  /new/output/run --from-run /existing/trusted/cache_run
```

Optional repeated `--reference NAME=/path/to/core.json` arguments replace the
two default starting plans, in the given order. Preserve this order and all
inputs when reproducing a particular multistart search. The wrapper freezes a
source/configuration snapshot, checks the cache binding, saves input hashes,
runs repaired/packed starts, coordinate searches, 3x8000 plus up to 8x24000
annealing proposals and legal SLR relabeling. Only resource-feasible candidates
enter the final comparison. Scores within absolute 1e-6 prefer minimum summed
center displacement from the input core, then the stable candidate tag.

Outputs include `solution.json`, `export/`, `verification.json`,
`soft/solution.json`, `soft/regions.tcl`, `soft/soft_region_adapter.tcl`,
`soft/figures/regions.png` and `source/`. Cost/resource arithmetic and the
soft-extension rule are independently checked. The output directory must be
new; completed runs are not overwritten.

The Tcl adapter is an integration component for the existing implementation
flow. Actual application also requires the matching private `membership.tsv`,
native Vivado, and the existing `f96` helpers used by `adapter.tcl`; the cache
search neither creates cells nor invokes placement, fanout treatment or routing.

## Balanced partition entry points

The partition stage additionally requires KaHyPar 1.3.7, its included `km1.ini`,
Gurobi for static-region initialization, and Matplotlib for its legacy plots.
Prepare a fresh `RUN/source` snapshot, `RUN/graph.pkl`, `RUN/cr.tsv`, and
`RUN/baseline` pointing to the original partition run as described in
[improvements.md](improvements.md). `PREVIOUS` is the completed three-step run.

The explicit stages are:

```sh
python3 RUN/source/balanced_generate.py RUN PREVIOUS
python3 RUN/source/balanced_search.py import RUN --previous PREVIOUS
# Evaluate candidate names with balanced_regions.py RUN NAME [NAME ...].
# balanced_search.py combine/merge/refine emits *_names.json for evaluation.
# balanced_deliver.py select RUN chooses among evaluated candidates.
# balanced_deliver.py deliver RUN --candidate NAME exports that module set.
```

Repeat evaluation after each composition/merge/refinement stage, as implemented
in `balanced_pipeline.py`. That legacy orchestration entry waits for
`generation_complete.json` and a successful `combine_first.exit` produced by
the external stage controller; it must not be invoked without those stages.
These algorithms retain the original graph/ownership/resource checks. Publishing
this code does not rerun partitioning or alter the frozen eleven memberships.

## Validation and publication boundary

Run the included tests with:

```sh
python3 -m unittest discover \
  -s FPGA_benchmark/netlist_hier_floorplan/connection_partition -p 'test_*.py' -v
```

Release validation also replays the current trusted eleven-module cache through
the published entry point and compares core geometry, objective, resource usage
and exact expanded CR sets with the 2026-09-22 result. Full netlists, DCPs, caches,
cell membership, resource/connection datasets, generated figures and experiment
outputs remain in private local/server records; only source, configuration,
tests, documentation and a source-hash manifest are published.

The earlier baseline/improvement manifests describe their own historical
commits. `release_9_22_manifest.json` identifies this release's source set.
