# Fixed-module timing-aware floorplan

This optional flow implements the 2026-09-19 request to keep the eleven S00-S10
modules and choose new resource-feasible regions using a raw timing-aware cost.
The original connectivity-only entry point and all historical exports remain
unchanged. This flow does not execute Vivado, edit the netlist or repartition.

## Frozen objective

`J = D_all + fixed_partition_cost + 10*C_critical + 100*P_square`.

- `D_all` is the existing weighted expected hypernet bounding span,
  `spanX + spanY + 4*spanSLR`, including internal-module nets.
- `C_critical` sums criticality-weighted expected directed atom-to-atom
  Manhattan distances with the same SLR coefficient 4. Repeated atom pairs
  use their maximum observed criticality, not their number of appearances.
- `P_square` sums `q_p * E[max(0,n_p-1)^2]` over distinct projected paths.
  `n_p` is the sum of absolute SLR differences along a same-cycle path.
  A repeated atom keeps the same location within a path. The expectation is
  outside the square; using the square of the expected crossing count is wrong.
- `q = 1 + 9*clip(1-slack_ns/0.5,0,1)` is fixed for the search.

No component is divided by a baseline cost, path count or total weight. The
coefficients are engineering starting values, not calibrated delay constants.
Resource-capacity-weighted independent atom locations are only a static proxy.
There is no prediction of WNS, congestion, clock skew or future replica trees.

`timing_feedback.py` maps the existing worst1000 routed path cache to the original
post-opt atoms, removes inserted fanout distribution helpers and resolves native
replicas through original-cell names and exact module ownership. It does not
query new timing. The complete original `n509453` broadcast is included in the
directed term, assigning unobserved branches the launch BRAM's maximum observed
criticality. This conservative propagation is distinguished from measured slack.

## Search and constraints

All four SLRs and multi-SLR rectangles are eligible. The existing candidate area
window and nine resource dimensions are retained: URAM <=100%, all other
dimensions <=70%, both per module and after contributions are summed in each CR.
Overlapping rectangles are legal. There is no equal-size or cell-balance target.

The search retains the old plan, enumerates feasible die permutations, generates
two joint centroid-surrogate MIP proposals, and performs exact-cost local moves
and region swaps. Every recorded candidate and the final ranking use the complete
static J. The MIP objective, bound and gap certify only its surrogate proposal;
the final result is the best recorded feasible plan, not a global optimum.

## Reproduction

Use a new eda070 experiment with an immutable `source/` snapshot and manifest.
`timing_prepare.py RUN` binds the existing graph, device and original eleven-module
export, and writes compact `feedback.json` and `netmodel.pkl`. This preparation is
explicitly case-specific and asserts the original S00-S10 membership. Run
`timing_search.py RUN` to create candidates and the selected unchanged-membership
`export/`. `timing_verify.py RUN` independently enumerates CR pairs and path SLR
assignments to check both old and new costs, resources and input hashes.

The existing `balanced_implementation/prepare.py EXPORT OUTPUT 11` validates the
original DCP and every leaf membership, and writes `membership.tsv`, `regions.tcl`
and a manifest for the existing implementation adapter. These are implementation
inputs, not a new placed or routed checkpoint. `regions.tcl` contains region data,
not a standalone XDC. A later authorized physical run must use the same source
DCP, fanout policy and timing constraints for a meaningful comparison.

`timing_report.py RUN` renders the seven-section report and old/new region,
LUT/URAM/DSP utilization and critical-path comparison figures. Use an environment
with Matplotlib; no new package installation is required on eda070.

Frozen experiment: `trtrs_modules11_timing_floorplan_20260919_sa23o5vf`.
Local evidence: `reports/trtrs_modules11_timing_floorplan_20260919_01` under
`FPGA_benchmark`. Tests: `python -m unittest test_timing_model test_balanced`.
