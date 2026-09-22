# Hot-edge soft Pblock expansion

`edge_padding_export.py RUN CORE_RUN_OR_IMPLEMENTATION_INPUT` prepares a new
implementation input from the verified **unexpanded J-selected core**. It does
not search a new floorplan or launch physical implementation. Inputs include
the core `implementation_input/`, module exports and device table.
Use a fresh RUN directory; keep the previous run immutable.

Accept any verified unexpanded core, including the original
`trtrs_modules11_directed_floorplan_20260919_SNodyXXL` or a newly solved core.
Preserve its selected geometry/J/parameters byte-for-byte in `core_solution.json`.
Do not inherit the separate S01 whole-SLR override or RAM>80% right-padding rule.
Reject already padded/overridden inputs to prevent this accidental composition.
The single any-resource>50% rule covers URAM too. A larger soft region never
feeds back into core candidate selection; resources and J are **not**
recomputed on the expanded envelope.

For each boundary CR of each module, sum the existing capacity-weighted resource
projections of **all** modules covering that CR. If any resource is strictly
above 50%, propose its four edge-adjacent CRs that are on the same SLR and have
no module coverage in the input plan. Zero available capacity is not usage;
resource-specific spare capacity in an already covered CR is not an empty CR.
Only one simultaneous pass is performed, with no diagonal/corner fill or
recursive propagation. The new threshold is not a density limit.

When several modules qualify for the same **core-empty** CR, all of them add it
independently. There is no winner, priority ordering or reservation by an earlier
module. Empty-CR membership and edge pressure always come from the immutable
core snapshot, never from another module's expansion. The target
does not need to contain the triggering resource: it is soft placement space,
including spill capacity for related LUT/FF logic. Record every trigger,
blocked neighbor, qualifying module and addition in `edge_padding.json`.

The `hot-edge-empty-cr-v2-shared` metadata records each new CR's `modules` and
supporting edge `evidence`. `added_unique_crs` counts distinct physical CRs;
`added_module_crs` counts module-to-new-CR allowances, including sharing;
`shared_new_crs` counts new CRs included by multiple modules. Each module records
`shared_added_crs`. Sorting only stabilizes output; it never chooses recipients.

Export exact CR unions. A partial row/column must not be replaced by its larger
bounding rectangle. The updated `balanced_implementation/adapter.tcl` supports
these unions with one or more CLOCKREGION rectangles and keeps IS_SOFT=true.
`regions.tcl` loads its bundled `soft_region_adapter.tcl`, updating only
`bi_ranges` and `bi_apply`, so existing implementation runners consume the exact
CR sets without filling holes. It does not override fanout/protection procedures.
The helper is included in the input manifest. Existing immutable experiment
code is not updated retroactively.
AMD command reference: https://docs.amd.com/r/JXswcrCHJROaHTz43h5g2Q/FW3hgWm5cHHoonLgmVwfiA

Original module memberships, post-opt DCP, search/capacity parameters and core
floorplan remain unchanged. The `core-only-v1` accounting schema separates:

- `planning_regions`: unchanged core CRs and their resource capacities.
- `regions`: exact soft Pblock geometry with `core_crs` and `padding_crs`.
  It deliberately has no `capacity` field: added CRs do not provide planning
  resources and receive no estimated module demand.
- `components`, `objective`, `families`, `overlap`, `total_module_crs`: unchanged
  core estimates. `uniform_overlap_pass` refers only to the core projection.
- `soft_geometry`: separate counts of allowed CRs, with no resource estimates.
- `soft_diagnostic_objective`: null; the envelope is not scored.

The core must pass its resource checks. The core search area cap applies before
export expansion. Heatmaps use the same core utilization after export, so adding
CRs never dilutes it. Show added CRs using orange cross-hatching and `EXT`, not a
resource percentage. They are selected soft allowances, not unused physical
sites or predicted actual occupancy. White zero and gray no-capacity cells stay
distinct. Actual resource usage requires a later placement readback.
