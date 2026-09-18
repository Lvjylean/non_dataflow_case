# Three-step cache-only partition experiment

The original `partition.py` and published `originalpart` baseline remain unchanged.
`improve.py` reads an existing complete graph cache and frozen candidate groups.
It does not run extraction, netlist optimization, timing, placement or routing.

## Predeclared comparisons

1. Start from the archived seed-0 pre-normalization groups. Compare unconditional
   merging against normalized-affinity thresholds 0.005, 0.01 and 0.02. Affinity
   is the shared hyperedge weight divided by the smaller total incident weight.
   All nets, including ordinary high-fanout data nets, remain in real metrics.
   Threshold 0.01 is the main stage-2 input; others assess sensitivity.
2. Identify exact-parent logical cores with 32-30000 cells and internal/incident
   net weight >=0.5. Dedicated atoms remain indivisible. Use artificial hierarchy
   hyperedges weighted at 2% of each core's internal real-net weight (integer
   rounding, minimum one quarter-net unit). Compare two positive-gain boundary
   passes against an otherwise identical real-net-only refinement. No cell is
   fixed by hierarchy. Each run has a 2% real-km1 budget relative to its input.
3. Recombine the stage-2 descendants of the largest-URAM baseline parent for a
   local KaHyPar search, comparing k=2 and k=4 with seeds 0 and 1. The dominant
   heterogeneous resource is bounded by min(one SLR, 1.25*demand/k), using the
   existing scalar resource encoding. This is a targeted resource constraint,
   not a claim of native multidimensional KaHyPar support. Retain cell cap150000.
   Evaluate actual static device CR geometry and summed overlap budgets for all
   modules; URAM may use 100%, other modeled resources 70%. Use the same rules
   for every baseline and candidate. An additional whole-SLR 50% parent policy
   is not imposed in this new static rectangular-region comparison.

The published baseline's historical pre-normalization groups already include a
resource-driven split. Step 1 therefore measures whether to retain that existing
split; it does not claim that selective merging can discover new boundaries.
Fresh local splitting is separately identified as step 3.

## Exploratory follow-up

When the predeclared atom-only refinement made no moves, `core_adjust.py` added
simultaneous whole-core relocation. This evaluates exact real and synthetic
hyperedge gains, including nets incident to several moved atoms. It explores
core cohesion >=0.2 and strengths 0, 0.02 and 0.10, with the same final 2% real
km1 budget. Report this separately from the predeclared comparison; use the
original core set for common metrics and the expanded set for diagnostic metrics.
The search never requires a core to move or assumes that hierarchy preservation
is more valuable than actual connectivity. Top-direct cells remain free atoms.
Repeat this exploration on the retained six-group affinity-0.02 candidate to
test whether splitting creates useful boundary-refinement headroom.

The initial static model could place siblings in nonadjacent SLRs. The
`--couple-families` comparison therefore keeps majority descendants of the
same baseline parent within a common consecutive SLR window. Its length is
the minimum aggregate-resource-feasible length under the same utilization
limits. This is an explicit planning preference, not a timing proof or a claim
that baseline partitions are immutable functional boundaries. Earlier results
remain separate from `static_coupled_regions.json`.

`resource_regroup.py` also examines all three pairings of a four-child proposal.
A pair can merge only when its combined resource vector fits an actual one-SLR
CR rectangle and the emergency cell cap. Complete connectivity is recomputed;
individual fit does not substitute for subsequent joint overlap feasibility.
The lowest-cut regrouping receives the same whole-core refinement comparison.

## Execution layout

Use a fresh server run directory with `graph.pkl` pointing to the complete
immutable cached graph, `baseline` pointing to the completed original run,
and `cr.tsv` copied from the same device's static resource inventory. Copy the
source files and `km1.ini` into `RUN/source`. Run the partition commands in the
existing KaHyPar 1.3.7 environment and the static solver in the existing Gurobi
environment. No dependency installation or Vivado invocation is needed.

```sh
python3 source/improve.py stage12 RUN
python3 source/improve.py split RUN --pieces 2 --seed 0
python3 source/improve.py split RUN --pieces 4 --seed 0
# Repeat the local searches with seed 1 for the declared comparison.
python3 source/core_adjust.py RUN stage1_affinity_0.02
python3 source/resource_regroup.py RUN stage3_k4_s1
python3 source/static_regions.py RUN RUN/cr.tsv baseline stage1_affinity_0.02_corebatch_0.1 --couple-families --output-name static_coupled_regions.json
```

`finish_improved.py RUN CANDIDATE` exports complete leaf membership, resource
and connection tables and a static region plan. New module IDs use the `N`
prefix; baseline-parent provenance keeps the original `P` prefix. The exporter
requires a feasible coupled static result. `plot_static_comparison.py` renders
resource estimates, clearly distinguished from actual placement.

## Interpretation and promotion gate

Record real cut/km1 separately from synthetic hierarchy penalties. Check unique
leaf ownership, conserved resource totals, dedicated atoms and actual resource
limits before using any candidate. Module count, near-cap count and cell spread
are diagnostics, not an equal-size objective. Never select solely by raw km1
across different counts. Static region feasibility is a resource/planning proxy,
not placement, routing, SLL or timing evidence. Generated data stays local/server.

Only publish a new source version after measured benefits and limitations are
documented against `originalpart`. Preserve baseline records and other active
physical experiments. Failed or dominated candidates remain experimental evidence.
