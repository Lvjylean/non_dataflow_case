# Intact-chain grouping and regional guidance

This optional stage runs **after** logical partition selection and parent
floorplanning. It preserves every logical module owner and parent core/envelope.
It does not add congestion penalties, routed density fitting, pipelines, driver
copies or placement/routing.

## Grouping and region assignment

Eligible parents have at least 16 CRs and 16 validated joint chains by default.
Internal candidate grids target about 8 CRs per child, with up to eight children
and twelve layouts. Tiles are clipped to the exact parent core, separated at
SLR boundaries, and screened against every resource. This finite candidate
family is a first implementation, not a claim that fixed slots are optimal.

For each layout, assign each complete chain to one tile or to its original
parent region. Chains assigned to the same tile form a physical group. Unmoved
chains and all other parent logic form a remainder, retaining the parent region.
Protected operators and physical atoms cannot split. Group count and membership
are solver results, not manually listed bank IDs.

For every resource-bearing CR c and resource r, enforce

```
sum(fixed_node_demand[r] / capacity(region, r), for fixed nodes covering c)
 + sum(x[j,t] * chain_demand[j,r] / capacity(tile[t],r), for tiles covering c)
 <= resource_limit[r]
sum_t x[j,t] = 1; x[j,t] is binary.
```

The fixed part includes the remainder and all other modules. Parent total demand
is not added a second time. A tile with no demanded resource cannot host a chain.
Limits remain 70% for non-URAM and 100% for URAM. Simultaneous assignment matters:
an individual move can temporarily overflow even when a complete reassignment
is feasible. Each MIP has a 30-second limit and the full-parent fallback.

The assignment proposal uses existing directed sink-pin communication costs,
including internal branches, with resource-capacity-weighted expected locations.
Connections to other moving chains are linearized at their current locations.
After assignment, recompute **all** directed branches exactly under that same
probability model, and accept only a resource-valid decrease. Whole-parent
fallback remains available if no candidate improves it. This is a bounded
heuristic, not a global optimum or measured wirelength.

The subordinate objective is

```
J_guidance = directed_weight * sum_b w_b E[dx + dy + slr_weight * ds]
           + branch_square_weight * sum_b w_b E[max(0, ds - 1)^2].
```

It uses the current coefficients 1 / 8 / 32, without normalization. The original
parent J and partition C+L stay frozen. D_hyper is not silently rebuilt with new
logical boundaries; the output explicitly does **not** claim a new full parent J.
The expanded all-parent assignment reproduces the parent's directed cost, making
the before/after guidance comparison independent of physical group labels.

## Output and integration

```
python3 structure_pipeline.py floorplan /absolute/partition_run --chain-guidance
# Or reuse a completed parent floorplan without rerunning it:
python3 chain_guidance.py /absolute/partition_run /absolute/new_guidance_output
```

The first form keeps the parent result at `implementation_input/` and writes the
guided result at `chain_guidance/implementation_input/`. The second form requires
the run's validated `floorplan/` and `implementation_input/`.

Logical parents remain S00, S01, etc. Physical groups are S00G00, S00G01, etc.;
the remainder keeps S00 if nonempty. Each original leaf receives exactly one
physical Pblock owner. This avoids trying to place the same leaf in a parent
and child Pblock simultaneously. `physical_to_logical.json` and `logical_export/`
preserve logical identity; this is an ownership hierarchy, not reconstructed RTL.
Physical resources, connections and leaf tables are rebuilt from the original
graph. Joint-chain identities and protection checks are carried into the export.

Other parent core and soft geometry is unchanged. Child soft extensions follow
the current shared core-empty / edge50 rule and stay inside their parent's soft
envelope. Extensions add geometry only, never resource capacity. The remainder's
full-parent region can overlap child regions; resource accounting sums their
disjoint memberships. Soft constraints cannot guarantee actual chain locality.

Review `summary.json`, `chain_assignments.json`, `implementation_input/manifest.json`
and `figures/chain_regions.png`. A high number of fallback chains is an explicit
limitation, not silently represented as successful subdivision. Validate actual
group placement, local congestion and timing in a subsequent physical experiment.
