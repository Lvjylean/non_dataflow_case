# Functional modules with a balanced static planning objective

Status: cache experiment, not placement/routing or a timing-quality claim.
The user requests final modules with logical cohesion and useful floorplan
granularity. Original hierarchy is provenance and soft preference. Resource
types do not prescribe module boundaries. Existing entry points stay unchanged.

## Frozen calibration protocol

`balanced_config.json` fixes defaults before new candidate results. Identify
exact-parent cores of 8–32768 cells with internal/incident edge weight >=0.2.
Give their synthetic hyperedges 0.1 times internal real-net weight. These cores
are soft preferences, not immutable blocks. Their coverage is reported explicitly.

Apply the same local two-way proposal to every original block, with seeds 0/1.
The 85% parent-cell upper bound only generates nontrivial proposals; there is no
final equal-size requirement. Add resource-driven proposals where heterogeneous
demand exceeds one SLR. Reuse archived four-child proposals as additional
alternatives, fully rescoring them. Combine beneficial local proposals, attempt
reverse merges and whole-core/atom refinement. This is a bounded neighborhood
search starting from the archived partition, not unrestricted/global optimality.

Admit candidates when additional full-graph km1 is <=2.5% of total real-net
weight and additional cuts inside every original block are <=10% of its incident
net weight. The former is not a 2.5% increase over baseline km1. Test 0.5x/2x
budgets as sensitivity. These are engineering calibration settings, not user
requirements, discovered physical limits, or evidence of cross-case generality.

## Fixed-atom physical estimator

Every cached real hyperedge retains its distinct dedicated atoms, even when
all atoms belong to the same candidate module. A fixed resource classification
of each atom determines a capacity-weighted location distribution over its
module's candidate clock regions. For each axis and integer boundary t,

`E[span] = sum_t (1 - product_i F_i(t) - product_i (1-F_i(t)))`.

Locations are independent draws in this estimator. Sum all weighted hypernet
spans, using X/Y coefficient 1 and SLR coefficient 4. There is no module-count
discount on internal nets and no separate penalty for a module merely covering
several SLRs. Assigning the same location distributions under different module
labels leaves the physical score unchanged; an analytical test checks this.

Joint resource limits retain URAM=100% and other modeled resources=70%. Regions
are rectangles of actual CRs, retaining all SLR spans within 1.5x the minimum
feasible area plus 4 CRs. An initial MIP minimizes exact internal-net expected
cost plus a centroid boundary proxy, then coordinate refinement minimizes the
full hypernet expectation. All reported physical scores use the full estimator.
The initializer's MIP gap is not a certificate for the final objective.

Composite score:

`J = E[X span + Y span + 4*SLR span] + 2*real_km1 + 2*soft_core_km1 + 0.0025*all_net_weight*module_count`.

Choose among admitted candidates; within 1% of the lowest J prefer fewer units,
then lower real km1, lower core loss and score. Re-rank the fixed region plans
under budget, SLR, cut and complexity variations; label this limited sensitivity
scope clearly rather than claiming all variants were physically reoptimized.

## Material limits

Uniform/capacity-proportional atom distributions omit correlation and detailed
packing, and can overestimate intra-module distances and favor smaller regions.
This is a transparent static heuristic, not a measured wirelength, SLL count,
congestion estimate, lower bound, or proof of timing improvement. Dedicated-atom
internal site geometry is not expanded. Clock/constant nets remain infrastructure;
external port locations are unknown. No new STA, extraction, replicas or P&R.
Functional role labels must cite hierarchy/naming/connectivity evidence and mark
inferences; storage/compute/fetch/read categories are not asserted from resource
counts alone. Generated artifacts remain local/server-side.
